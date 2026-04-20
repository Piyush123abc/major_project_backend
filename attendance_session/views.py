# attendance_session/views.py
import random 
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.utils import timezone
from attendance_session.models import SecurityAnomaly
from user.models import Student, Teacher, Classroom, AttendanceRecord
from user.permission import IsSuperUser, IsTeacher, IsStudent
import secrets
from attendance_system.utils import send_fcm_notification
from django.utils.timezone import localtime, timedelta

# ---------------------------
# Session storage (in-memory)
# ---------------------------
# Key: classroom_id
# Value: SessionObject instance
sessions = {}

# ---------------------------
# Graph-based Session Object
# ---------------------------
class SessionObject:
    """Represents an active attendance session using an undirected graph."""
    def __init__(self, classroom_id, teacher_uid, student_uids):
        self.classroom_id = classroom_id
        self.teacher_uid = teacher_uid
        
        # Initialize an Adjacency List for the graph
        self.graph = {uid: set() for uid in student_uids}
        self.graph[teacher_uid] = set()
        
        # Students without devices (exception list)
        self.exception_list = set()
        self.marked_exceptions = set()
        
        # Track student UIDs acting as verified master nodes
        self.master_nodes = set()
        
        # Track who has received the "Connected" notification
        self.notified_uids = set()
        
        # ==========================================
        # CRYPTOGRAPHIC SESSION DATA
        # ==========================================
        self.k_class = secrets.token_bytes(16).hex() 
        self.student_crypto_data = {}  
        self.node_id_to_uid = {}       
        
        self.node_id_to_uid[0] = teacher_uid
        # PERFECT 1-to-N COUNTER
        for index, uid in enumerate(student_uids, start=1):
            seed = secrets.token_bytes(16).hex()
            node_id = index 
            
            self.student_crypto_data[uid] = {
                'session_seed': seed,
                'node_id': node_id
            }
            self.node_id_to_uid[node_id] = uid
            
        # ==========================================
        # GPS DATA(FALLBACK VERSION)
        # ==========================================
        self.latitude = None
        self.longitude = None
        
        
    # --- DEBUG HELPER ---
    def print_debug_state(self, trigger_event, newly_marked=None):
        print("\n=========================================")
        print(f"📍 DEBUG TRIGGERED BY: {trigger_event}")
        
        print("\n1. CURRENT GRAPH (Token Chain Adjacency List):")
        for uid, connections in self.graph.items():
            # Fetch the temporary ID for the main node
            temp_id = self.student_crypto_data.get(uid, {}).get('node_id', 'TEACHER')
            
            # Fetch the temporary IDs for all connected nodes
            formatted_connections = []
            for conn_uid in connections:
                conn_temp_id = self.student_crypto_data.get(conn_uid, {}).get('node_id', 'TEACHER')
                formatted_connections.append(f"({conn_temp_id}) {conn_uid}")
            
            if formatted_connections:
                print(f"   ({temp_id}) {uid} <--> {formatted_connections}")
            else:
                print(f"   ({temp_id}) {uid} <--> []  (No connections yet)")
        
        print("\n2. MASTER NODES (Confirmed Starting Points):")
        formatted_masters = []
        for m_uid in self.master_nodes:
            m_temp_id = self.student_crypto_data.get(m_uid, {}).get('node_id', 'TEACHER')
            formatted_masters.append(f"({m_temp_id}) {m_uid}")
        print(f"   {formatted_masters if formatted_masters else 'None yet'}")
        
        print("\n3. MARKED FROM EXCEPTION LIST:")
        if newly_marked is not None:
            print(f"   Just Marked: {newly_marked}")
        else:
            print(f"   Total Marked: {list(self.marked_exceptions) if self.marked_exceptions else 'None yet'}")
        
        print("\n4. NEW PENDING EXCEPTION LIST (To be pulled):")
        pending = self.exception_list - self.marked_exceptions
        print(f"   {list(pending) if pending else 'No pending exceptions!'}")
        print("=========================================\n")
        
    # ---------------------------
    # 
    # ---------------------------
    def check_and_notify_new_connections(self):
        visited = set()
        queue = [self.teacher_uid] + list(self.master_nodes)
        
        for node in queue:
            if node in self.graph:
                visited.add(node)

        idx = 0
        while idx < len(queue):
            current = queue[idx]
            idx += 1
            for neighbor in self.graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        newly_verified = []
        for uid in visited:
            if uid != self.teacher_uid and uid not in self.notified_uids:
                newly_verified.append(uid)
                self.notified_uids.add(uid)

        if newly_verified:
            from user.models import Student
            students = Student.objects.filter(uid__in=newly_verified).values_list('fcm_token', flat=True)
            tokens = [t for t in students if t]
            
            if tokens:
                send_fcm_notification(
                    fcm_tokens=tokens,
                    title="Chain Secured! ✅",
                    body="You are now connected to the Teacher's network.",
                    data_payload={"type": "connection_verified", "classroom_id": str(self.classroom_id)}
                )
    
    
    # ---------------------------
    # Token Passing Logic (Edge Creation)
    # ---------------------------
    def pass_token(self, from_uid, to_uid):
        # FIX: Type Mismatch Safety (String from JSON vs Int/UUID in DB graph)
        actual_from = next((k for k in self.graph if str(k) == str(from_uid)), None)
        actual_to = next((k for k in self.graph if str(k) == str(to_uid)), None)

        if actual_from is None or actual_to is None:
            raise ValueError(f"Invalid from_uid ({from_uid}) or to_uid ({to_uid})")

        # Create an undirected edge (A -> B and B -> A)
        self.graph[actual_from].add(actual_to)
        self.graph[actual_to].add(actual_from)

        # Fetch the temporary node IDs for the clean print statement
        from_node = self.student_crypto_data.get(actual_from, {}).get('node_id', 'TEACHER')
        to_node = self.student_crypto_data.get(actual_to, {}).get('node_id', 'TEACHER')

        self.print_debug_state(f"Token Pass: ({from_node}) {actual_from} <-> ({to_node}) {actual_to}")
        
        self.check_and_notify_new_connections()

    # ---------------------------
    # Exception Handling
    # ---------------------------
    def add_exception(self, student_uid):
        actual_uid = next((k for k in self.graph if str(k) == str(student_uid)), None)
        if actual_uid is None:
            raise ValueError("Invalid student UID")
        self.exception_list.add(actual_uid)

    def get_exception_list(self):
        pending_list = self.exception_list - self.marked_exceptions
        return list(pending_list)

    # ---------------------------
    # Finalize Attendance (BFS Traversal)
    # ---------------------------
    def finalize_attendance(self, present_uids_from_exception=[]):
        for uid in present_uids_from_exception:
            actual_uid = next((k for k in self.graph if str(k) == str(uid)), None)
            if actual_uid and actual_uid in self.exception_list:
                self.graph[actual_uid].add(self.teacher_uid)
                self.graph[self.teacher_uid].add(actual_uid)

        visited = set()
        queue = [self.teacher_uid]
        visited.add(self.teacher_uid)

        for master_uid in self.master_nodes:
            if master_uid in self.graph and master_uid not in visited:
                queue.append(master_uid)
                visited.add(master_uid)

        while queue:
            current = queue.pop(0)
            for neighbor in self.graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        attendance = {}
        for uid in self.graph:
            if uid == self.teacher_uid:
                continue
            attendance[uid] = (uid in visited)
            
        return attendance


# ---------------------------
# Teacher-only Endpoints
# ---------------------------
class StartSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        teacher_uid = request.user.teacher.uid

        if classroom_id in sessions:
            return Response({"error": "Session already active"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            classroom = Classroom.objects.get(id=classroom_id)
        except Classroom.DoesNotExist:
            return Response({"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        student_uids = list(classroom.enrollments.all().values_list('student__uid', flat=True))
        session = SessionObject(classroom_id, teacher_uid, student_uids)
        sessions[classroom_id] = session
        return Response({"message": f"Session started for classroom {classroom_id}"})

class GetTeacherSessionCredentialsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, classroom_id):
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "k_class": session.k_class,
            "session_seed": "",       
            "node_id": 0
        }, status=status.HTTP_200_OK)

class GetExceptionListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, classroom_id):
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        exception_uids = session.get_exception_list()
        students = Student.objects.filter(uid__in=exception_uids).select_related('user')

        exception_list = [
            {"uid": student.uid, "username": student.user.username}
            for student in students
        ]

        return Response({"exception_list": exception_list})

class MarkExceptionPresentView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        present_uids = request.data.get("present_uids", [])
        if not present_uids:
            return Response({"error": "No UIDs provided"}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            classroom = Classroom.objects.get(id=classroom_id)
        except Classroom.DoesNotExist:
            return Response({"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        enrolled_uids = set(classroom.enrollments.all().values_list('student__uid', flat=True))

        for uid in present_uids:
            actual_uid = next((k for k in enrolled_uids if str(k) == str(uid)), None)
            if not actual_uid:
                return Response({"error": f"UID {uid} not enrolled"}, status=status.HTTP_400_BAD_REQUEST)
            
            session.graph[actual_uid].add(session.teacher_uid)
            session.graph[session.teacher_uid].add(actual_uid)
            session.marked_exceptions.add(actual_uid)

        session.print_debug_state("Teacher Marked Exception List Updates", newly_marked=present_uids)

        return Response({"message": f"{len(present_uids)} students marked present"})

class FinalizeSessionView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        present_uids_from_exception = request.data.get("present_uids", [])
        
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            classroom = Classroom.objects.get(id=classroom_id)
        except Classroom.DoesNotExist:
            return Response({"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        results = session.finalize_attendance(present_uids_from_exception)
        today = timezone.now().date()
        
        present_tokens = []
        absent_tokens = []
        
        current_time = localtime(timezone.now()).strftime("%I:%M %p") 
        class_name = getattr(classroom, 'name', f"Class {classroom_id}")
        
        for uid, is_present in results.items():
            student = Student.objects.get(uid=uid)
            AttendanceRecord.objects.create(
                student=student,
                classroom=classroom,
                date=today,
                status="PRESENT" if is_present else "ABSENT"
            )
            
            if student.fcm_token:
                if is_present:
                    present_tokens.append(student.fcm_token)
                else:
                    absent_tokens.append(student.fcm_token)
                    
        # --- UPGRADED: Detailed Notifications ---
        if present_tokens:
            send_fcm_notification(
                present_tokens, 
                "Attendance Finalized ✅", 
                f"You were marked PRESENT for {class_name} at {current_time}.", 
                {"type": "final", "status": "present"}
            )
            
        if absent_tokens:
            send_fcm_notification(
                absent_tokens, 
                "Attendance Finalized ❌", 
                f"You were marked ABSENT for {class_name} at {current_time}.", 
                {"type": "final", "status": "absent"}
            )

        del sessions[classroom_id]

        total_students = classroom.enrollments.count()
        total_present = sum(1 for status in results.values() if status)
        total_absent = total_students - total_present

        return Response({
            "message": f"Attendance finalized for classroom {classroom_id}",
            "summary": {
                "total_students": total_students,
                "present": total_present,
                "absent": total_absent,
            }
        })

class ActiveSessionsView(APIView):
    permission_classes = [permissions.IsAuthenticated, (IsTeacher | IsSuperUser)]

    def get(self, request):
        return Response({"active_sessions": list(sessions.keys())})

class AddMasterNodeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        student_uid = request.data.get("uid")
        if not student_uid:
            return Response({"error": "Student UID required"}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        actual_uid = next((k for k in session.graph if str(k) == str(student_uid)), None)
        if not actual_uid:
            return Response({"error": "Student UID not found in this classroom"}, status=status.HTTP_400_BAD_REQUEST)

        session.master_nodes.add(actual_uid)
        session.print_debug_state(f"Added Master Node: {actual_uid}")
        
        session.check_and_notify_new_connections()
        
        return Response({"message": f"Student {actual_uid} added as a master node"})

class RemoveMasterNodeView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        student_uid = request.data.get("uid")
        if not student_uid:
            return Response({"error": "Student UID required"}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        actual_uid = next((k for k in session.master_nodes if str(k) == str(student_uid)), None)
        if actual_uid:
            session.master_nodes.remove(actual_uid)
            session.print_debug_state(f"Removed Master Node: {actual_uid}")
            return Response({"message": f"Student {actual_uid} removed from master nodes"})
        else:
            return Response({"error": "Student is not a master node"}, status=status.HTTP_400_BAD_REQUEST)

class ListMasterNodesView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, classroom_id):
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        students = Student.objects.filter(uid__in=session.master_nodes).select_related('user')
        
        master_list = [
            {"uid": student.uid, "username": student.user.username}
            for student in students
        ]

        return Response({"master_nodes": master_list})



class SetTeacherGPSView(APIView):
    """Allows the teacher to set or update their GPS anchor for the session."""
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def post(self, request, classroom_id):
        lat = request.data.get("latitude")
        lng = request.data.get("longitude")

        if lat is None or lng is None:
            return Response({"error": "Latitude and longitude are required."}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session found."}, status=status.HTTP_404_NOT_FOUND)

        # Ensure only the teacher who started the session can update the GPS
        if str(session.teacher_uid) != str(request.user.teacher.uid):
            return Response({"error": "Unauthorized. Only the session creator can set GPS."}, status=status.HTTP_403_FORBIDDEN)

        try:
            session.latitude = float(lat)
            session.longitude = float(lng)
            session.print_debug_state(f"Teacher GPS Set: {session.latitude}, {session.longitude}")
            return Response({"message": "Teacher GPS coordinates anchored successfully."}, status=status.HTTP_200_OK)
        except ValueError:
            return Response({"error": "Invalid coordinate format."}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------
# Student Endpoints
# ---------------------------
class GetSessionCredentialsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get(self, request, classroom_id):
        try:
            student_uid = request.user.student.uid
        except Student.DoesNotExist:
            return Response({"error": "User is not a student"}, status=status.HTTP_403_FORBIDDEN)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_404_NOT_FOUND)

        actual_uid = next((k for k in session.student_crypto_data if str(k) == str(student_uid)), None)
        if not actual_uid:
            return Response({"error": "Not enrolled in active session"}, status=status.HTTP_403_FORBIDDEN)

        crypto_data = session.student_crypto_data[actual_uid]

        return Response({
            "k_class": session.k_class,
            "session_seed": crypto_data['session_seed'],
            "node_id": crypto_data['node_id'] 
        }, status=status.HTTP_200_OK)


class PassTokenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, classroom_id):
        from_uid = request.data.get("from_uid")
        provided_to_id = request.data.get("to_uid")

        if not from_uid or not provided_to_id:
            return Response({"error": "from_uid and to_uid are required in the payload"}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active attendance session"}, status=status.HTTP_400_BAD_REQUEST)

        actual_to_uid = None
        mode = "fallback"

        try:
            lookup_id = int(provided_to_id)
            if lookup_id in session.node_id_to_uid:
                actual_to_uid = session.node_id_to_uid[lookup_id]
                mode = "secure"
                print(f"✅ Secure Mode: Translated Temp ID {lookup_id} to Permanent UID {actual_to_uid}")
            else:
                actual_to_uid = provided_to_id
                print(f"ℹ️ Fallback Mode: Using provided Integer UID {actual_to_uid} directly")
        except (ValueError, TypeError):
            actual_to_uid = provided_to_id
            print(f"ℹ️ Fallback Mode: Using provided String UID {actual_to_uid} directly")

        if str(from_uid) == str(actual_to_uid):
            return Response({"error": "You cannot verify yourself"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session.pass_token(from_uid, actual_to_uid)
            return Response({
                "message": "Attendance Verified",
                "verified_with": actual_to_uid, 
                "mode": mode
            }, status=status.HTTP_200_OK)
            
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        
class AddExceptionView(APIView):
    permission_classes = [permissions.IsAuthenticated] 

    def post(self, request, classroom_id):
        student_uid = request.data.get("uid")
        if not student_uid:
            return Response({"error": "UID is required."}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": f"No active session found."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session.add_exception(student_uid)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"message": f"Student successfully added to exception list."}, status=status.HTTP_200_OK)

class ClassroomSessionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, classroom_id):
        if classroom_id in sessions:
            return Response({"active": True, "message": "Attendance session is active"})
        else:
            return Response({"active": False, "message": "No active attendance session"}, status=status.HTTP_200_OK)
        

class GetTeacherGPSView(APIView):
    """Allows enrolled students to fetch the teacher's GPS anchor for distance calculation."""
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get(self, request, classroom_id):
        try:
            student_uid = request.user.student.uid
        except Student.DoesNotExist:
            return Response({"error": "User is not a student"}, status=status.HTTP_403_FORBIDDEN)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session found."}, status=status.HTTP_404_NOT_FOUND)

        # Verify the student is actually part of this session
        actual_uid = next((k for k in session.student_crypto_data if str(k) == str(student_uid)), None)
        if not actual_uid:
            return Response({"error": "Not enrolled in this active session."}, status=status.HTTP_403_FORBIDDEN)

        if session.latitude is None or session.longitude is None:
            return Response({"error": "Teacher GPS coordinates have not been set yet."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "latitude": session.latitude,
            "longitude": session.longitude
        }, status=status.HTTP_200_OK)
        
        
# ---------------------------
# Security Anamoly
# ---------------------------
def create_anomaly_report(student, anomaly_type_int, device_id="Unknown", metadata=None):
    """
    Internal engine to log threats and notify the user. 
    Accepts a 'student' object instance.
    """
    time_threshold = timezone.now() - timedelta(hours=24)
    
    # 1. Check deduplication (Prevent notification spam)
    if SecurityAnomaly.objects.filter(
        student=student, 
        anomaly_type=anomaly_type_int, 
        timestamp__gte=time_threshold
    ).exists():
        print(f"DEBUG [Anomaly Engine]: Ignored. {student.uid} already triggered this anomaly type in the last 24h.")
        return {"status": "ignored", "notification_sent": False}

    # 2. Create the anomaly record
    anomaly = SecurityAnomaly.objects.create(
        student=student,
        anomaly_type=anomaly_type_int,
        device_id=device_id,
        metadata=metadata or {}
    )

    notification_sent = False

    # 3. Fire the FCM Notification
    if student.fcm_token:
        print(f"DEBUG [Anomaly Engine]: FCM Token found for {student.uid}. Attempting dispatch...")
        
        anomaly_label = anomaly.get_anomaly_type_display() 
        current_time = localtime(anomaly.timestamp).strftime("%I:%M %p")
        
        try:
            send_fcm_notification(
                fcm_tokens=[student.fcm_token],
                title="Security Alert ⚠️",
                body=f"Protocol breach logged: {anomaly_label} detected at {current_time}.",
                data_payload={
                    "type": "security_anomaly",
                    "anomaly_id": str(anomaly.id),
                    "anomaly_label": anomaly_label,
                    "timestamp": current_time
                }
            )
            notification_sent = True
            print("DEBUG [Anomaly Engine]: Notification successfully handed off to FCM util.")
        except Exception as e:
            print(f"DEBUG [Anomaly Engine]: FAILED to send notification. Error: {str(e)}")
            
    else:
        print(f"DEBUG [Anomaly Engine]: SKIPPED notification. Student {student.uid} has no FCM token in the database.")

    # 4. Return detailed state
    return {
        "status": "success", 
        "anomaly_id": anomaly.id,
        "notification_sent": notification_sent
    }
    
class FrontendAnomalyReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # 🔒 Grab the actual Student instance attached to the logged-in User
        student_instance = request.user.student 
        
        anomaly_type_int = request.data.get('anomaly_type') 
        device_id = request.data.get('device_id', 'Unknown')
        context = request.data.get('context', {})

        if not anomaly_type_int:
            return Response({"error": "Missing anomaly type"}, status=status.HTTP_400_BAD_REQUEST)

        # Pass the instance directly
        create_anomaly_report(student_instance, anomaly_type_int, device_id, context)

        return Response({"message": "Report processed"}, status=status.HTTP_200_OK)
    
class AdminSessionStateView(APIView):
    """
    God-mode view for SuperAdmins to monitor the live BLE mesh.
    Polls the in-memory 'sessions' object and maps UIDs to real names.
    """
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def get(self, request, classroom_id):
        # 1. Check if the session is currently live in RAM
        session = sessions.get(classroom_id)
        if not session:
            return Response({
                "active": False, 
                "message": "No active attendance session for this classroom."
            }, status=status.HTTP_200_OK)

        # 2. Fetch classroom and student details to map UIDs to real Usernames
        try:
            classroom = Classroom.objects.get(id=classroom_id)
        except Classroom.DoesNotExist:
            return Response({"error": "Classroom not found"}, status=status.HTTP_404_NOT_FOUND)

        # Grab all enrolled students to map UIDs to Usernames for the UI
        enrolled_students = Student.objects.filter(
            enrollments__classroom=classroom
        ).select_related('user')
        
        uid_to_name = {str(student.uid): student.user.username for student in enrolled_students}
        
        # Add the teacher's UID to the name map
        teacher_username = getattr(classroom.teacher.user, 'username', "Teacher")
        uid_to_name[str(session.teacher_uid)] = teacher_username

        # 3. Build Nodes and Edges
        nodes = []
        edges = []
        seen_edges = set()

        # Iterate through the graph dictionary (keys are UIDs)
        for uid in session.graph.keys():
            str_uid = str(uid)
            
            # Determine Node Type for UI Styling
            if str_uid == str(session.teacher_uid):
                node_type = "teacher"
            elif uid in session.master_nodes:
                node_type = "master"
            else:
                node_type = "student"

            nodes.append({
                "id": str_uid,
                "label": uid_to_name.get(str_uid, f"Unknown ({str_uid[:4]})"),
                "type": node_type,
                "is_exception": uid in session.exception_list,
                "is_marked": uid in session.marked_exceptions
            })

        # Build Edges (Undirected pairs)
        for node_uid, connections in session.graph.items():
            for conn_uid in connections:
                # Sort the pair to ensure we don't send A->B AND B->A separately
                edge_pair = tuple(sorted([str(node_uid), str(conn_uid)]))
                
                if edge_pair not in seen_edges:
                    seen_edges.add(edge_pair)
                    edges.append({
                        "id": f"edge_{edge_pair[0]}_{edge_pair[1]}",
                        "source": edge_pair[0],
                        "target": edge_pair[1]
                    })

        # 4. FIXED TELEMETRY LOGIC
        # total_enrolled: Count from DB
        total_enrolled = enrolled_students.count()
        
        # total_connected: Count students who have at least ONE connection in the graph
        # We exclude the teacher from this count.
        total_connected = 0
        for uid, connections in session.graph.items():
            if str(uid) != str(session.teacher_uid):
                if len(connections) > 0:
                    total_connected += 1
        
        pending_exceptions = len(session.exception_list - session.marked_exceptions)

        return Response({
            "active": True,
            "telemetry": {
                "total_enrolled": total_enrolled,
                "total_connected": total_connected,
                "orphaned": total_enrolled - total_connected,
                "master_nodes_count": len(session.master_nodes),
                "pending_exceptions": pending_exceptions
            },
            "graph": {
                "nodes": nodes,
                "edges": edges
            }
        }, status=status.HTTP_200_OK)
        
        
       
        
class SimulateMeshStepView(APIView):
    """God-Mode endpoint to simulate BLE mesh growth for presentations."""
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    def post(self, request, classroom_id):
        # We import sessions here to access the live RAM dictionary
        from attendance_session.views import sessions 
        
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session found."}, status=400)

        all_uids = list(session.graph.keys())
        if len(all_uids) < 3:
            return Response({"message": "Not enough students enrolled to simulate."})

        edges_added = 0
        # Simulate 5 random connections happening in the room
        for _ in range(5):
            node_a = random.choice(all_uids)
            node_b = random.choice(all_uids)
            if node_a != node_b:
                session.graph[node_a].add(node_b)
                session.graph[node_b].add(node_a)
                edges_added += 1

        # Randomly assign a master node if none exist
        if not session.master_nodes and len(all_uids) > 1:
            candidates = [u for u in all_uids if str(u) != str(session.teacher_uid)]
            if candidates:
                session.master_nodes.add(random.choice(candidates))

        return Response({"message": f"Simulated {edges_added} new BLE connections!"})