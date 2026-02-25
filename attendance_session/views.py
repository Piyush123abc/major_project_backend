# attendance_session/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.utils import timezone
from user.models import Student, Teacher, Classroom, AttendanceRecord
from user.permission import IsTeacher, IsStudent

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
        # Track students from the exception list who have been marked present
        self.marked_exceptions = set()

    # --- DEBUG HELPER ---
    def print_debug_state(self, trigger_event, newly_marked=None):
        print("\n=========================================")
        print(f"📍 DEBUG TRIGGERED BY: {trigger_event}")
        
        print("\n1. CURRENT GRAPH (Token Chain Adjacency List):")
        # Print EVERY node in the graph, even if they have no connections yet
        for uid, connections in self.graph.items():
            if connections:
                print(f"   {uid} <--> {list(connections)}")
            else:
                print(f"   {uid} <--> []  (No connections yet)")
        
        print("\n2. MARKED FROM EXCEPTION LIST:")
        if newly_marked is not None:
            print(f"   Just Marked: {newly_marked}")
        else:
            print(f"   Total Marked: {list(self.marked_exceptions) if self.marked_exceptions else 'None yet'}")
        
        print("\n3. NEW PENDING EXCEPTION LIST (To be pulled):")
        pending = self.exception_list - self.marked_exceptions
        print(f"   {list(pending) if pending else 'No pending exceptions!'}")
        print("=========================================\n")

    # ---------------------------
    # Token Passing Logic (Edge Creation)
    # ---------------------------
    def pass_token(self, from_uid, to_uid):
        """
        Create a bidirectional edge between sender and receiver.
        """
        # Check existence in graph
        found_from = from_uid in self.graph
        found_to = to_uid in self.graph

        if not found_from or not found_to:
            raise ValueError("Invalid from_uid or to_uid")

        # Create an undirected edge (A -> B and B -> A)
        self.graph[from_uid].add(to_uid)
        self.graph[to_uid].add(from_uid)

        # Trigger Debug Output
        self.print_debug_state(f"New Token Pass Received ({from_uid} -> {to_uid})")

    # ---------------------------
    # Exception Handling
    # ---------------------------
    def add_exception(self, student_uid):
        """Add a student to exception list (no device)."""
        if student_uid not in self.graph:
            raise ValueError("Invalid student UID")
        self.exception_list.add(student_uid)

    def get_exception_list(self):
        """Return the current exception list MINUS the ones already marked."""
        pending_list = self.exception_list - self.marked_exceptions
        return list(pending_list)

    # ---------------------------
    # Finalize Attendance (BFS Traversal)
    # ---------------------------
    def finalize_attendance(self, present_uids_from_exception=[]):
        """
        Mark attendance at session end using Breadth-First Search (BFS).
        """
        # 1. Link present exception students directly to teacher
        for uid in present_uids_from_exception:
            if uid in self.exception_list and uid in self.graph:
                self.graph[uid].add(self.teacher_uid)
                self.graph[self.teacher_uid].add(uid)

        # 2. Perform BFS starting from the teacher to find all connected nodes
        visited = set()
        queue = [self.teacher_uid]
        visited.add(self.teacher_uid)

        while queue:
            current = queue.pop(0)
            for neighbor in self.graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        # 3. Build the final attendance dictionary
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

class PassTokenView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, classroom_id):
        from_uid = request.data.get("from_uid")
        to_uid = request.data.get("to_uid")

        if not from_uid or not to_uid:
            return Response({"error": "from_uid and to_uid required"}, status=status.HTTP_400_BAD_REQUEST)

        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            session.pass_token(from_uid, to_uid)
            return Response({"message": f"Token passed {from_uid} <-> {to_uid}"})
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

class GetExceptionListView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request, classroom_id):
        session = sessions.get(classroom_id)
        if not session:
            return Response({"error": "No active session"}, status=status.HTTP_400_BAD_REQUEST)

        # Now fetching only the pending exceptions
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
            if uid not in enrolled_uids:
                return Response({"error": f"UID {uid} not enrolled"}, status=status.HTTP_400_BAD_REQUEST)
            # Create bidirectional edge with the teacher
            session.graph[uid].add(session.teacher_uid)
            session.graph[session.teacher_uid].add(uid)
            
            # Add to marked exceptions set so they are removed from pending list
            session.marked_exceptions.add(uid)

        # Trigger Debug Output
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

        # Compute attendance using BFS
        results = session.finalize_attendance(present_uids_from_exception)

        today = timezone.now().date()

        # Save to DB
        for uid, is_present in results.items():
            student = Student.objects.get(uid=uid)
            AttendanceRecord.objects.create(
                student=student,
                classroom=classroom,
                date=today,
                status="PRESENT" if is_present else "ABSENT"
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
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get(self, request):
        return Response({"active_sessions": list(sessions.keys())})

class ClassroomSessionStatusView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, classroom_id):
        if classroom_id in sessions:
            return Response({"active": True, "message": "Attendance session is active"})
        else:
            return Response({"active": False, "message": "No active attendance session"}, status=status.HTTP_200_OK)