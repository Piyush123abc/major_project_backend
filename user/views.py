from django.core.cache import cache
import secrets

from rest_framework import generics, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import (
    AbsenceProposal, Student, Teacher, Classroom, Enrollment, AttendanceRecord,
    GroupAbsenceProposal, GroupAbsenceParticipant
)
from .serializer import (
    AbsenceProposalSerializer,
    StudentSerializer,
    TeacherSerializer,
    ClassroomSerializer,
    EnrollmentSerializer,
    AttendanceRecordSerializer,
    GroupAbsenceProposalSerializer
)
from .permission import IsStudent, IsTeacher
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework_simplejwt.views import TokenObtainPairView
from .serializer import StudentTokenSerializer

class StudentLoginVerifyView(TokenObtainPairView):
    # This view now handles Password check + Signature check
    serializer_class = StudentTokenSerializer
    
# ------------------------------
# Registration Views
# ------------------------------

class StudentRegisterView(generics.CreateAPIView):
    serializer_class = StudentSerializer
    permission_classes = [permissions.AllowAny]


class TeacherRegisterView(generics.CreateAPIView):
    serializer_class = TeacherSerializer
    permission_classes = [permissions.AllowAny]


# ------------------------------
# Student Views
# ------------------------------

# ---------------------------------------------------------
# STEP 1 OF LOGIN: Generate the Cryptographic Challenge
# ---------------------------------------------------------
class GetLoginChallengeView(APIView):
    # Anyone can request a challenge, no token required yet!
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        # 1. Get the username from the Flutter app's request
        username = request.data.get('username')
        
        if not username:
            return Response(
                {"error": "Username is required to generate a challenge."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Generate a secure, random 32-byte hex string (the "nonce" or "challenge")
        # Example output: "a1b2c3d4e5f6..."
        challenge = secrets.token_hex(32)
        
        # 3. Save it in Django's RAM cache so we can verify it in Step 2.
        # We use the username as part of the cache key.
        # timeout=300 means the app has exactly 5 minutes to sign and return it.
        cache_key = f"login_challenge_{username}"
        cache.set(cache_key, challenge, timeout=300)

        # 4. Send the challenge back to the Flutter app
        return Response(
            {
                "message": "Challenge generated successfully.",
                "challenge": challenge
            }, 
            status=status.HTTP_200_OK
        )

# ---------------------------------------------------------
# DEVICE BINDING & ADMIN RESET VIEW (The Backdoor)
# ---------------------------------------------------------
class AdminResetDeviceView(APIView):
    # ✅ Only allow logged-in users with a valid JWT
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        new_public_key = request.data.get('public_key')
        admin_password = request.data.get('admin_password')

        # We no longer check for username here
        if not new_public_key or not admin_password:
            return Response(
                {"error": "Missing public_key or admin_password."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # 🚨 HARDCODED DEMO PASSWORD 🚨
        if admin_password != "1234":
            return Response(
                {"error": "Unauthorized. Invalid Admin Password."}, 
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            # ✅ Get the student securely from the JWT token
            student = Student.objects.get(user=request.user)
            
            # Update their key
            student.public_key = new_public_key
            student.save()
            
            return Response(
                {"message": f"Success! Device cryptographically bound to {request.user.username}."}, 
                status=status.HTTP_200_OK
            )
            
        except Student.DoesNotExist:
            return Response({"error": "Student profile not found."}, status=status.HTTP_404_NOT_FOUND)
        
class EnrollmentCreateView(generics.CreateAPIView):
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def perform_create(self, serializer):
        student = Student.objects.get(user=self.request.user)
        serializer.save(student=student)


class StudentEnrollmentListView(generics.ListAPIView):
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get_queryset(self):
        student = Student.objects.get(user=self.request.user)
        return Classroom.objects.filter(enrollments__student=student)


class StudentAttendanceListView(generics.ListAPIView):
    serializer_class = AttendanceRecordSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get_queryset(self):
        student = Student.objects.get(user=self.request.user)
        classroom_id = self.request.query_params.get("classroom_id")
        if classroom_id:
            return AttendanceRecord.objects.filter(student=student, classroom_id=classroom_id)
        return AttendanceRecord.objects.filter(student=student)


class ClassroomSearchView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get(self, request):
        code = request.query_params.get("code")
        if not code:
            return Response({"error": "Classroom code is required"}, status=status.HTTP_400_BAD_REQUEST)

        code = code.strip()

        if code.lower() == "all":
            # Return all classrooms
            classrooms = Classroom.objects.all()
            serializer = ClassroomSerializer(classrooms, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        # Partial or exact case-insensitive search
        classrooms = Classroom.objects.filter(code__icontains=code)
        if not classrooms.exists():
            return Response({"error": "No classrooms found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = ClassroomSerializer(classrooms, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    
class StudentClassroomSearchAPIView(APIView):
  #  permission_classes = [permissions.IsAuthenticated]  # or custom IsStudent

    def get(self, request):
        """
        GET /student/classrooms/?code=XYZ
        Returns classrooms whose code contains the search string.
        """
        code_query = request.query_params.get('code')
        if not code_query:
            return Response({"error": "Please provide a 'code' query parameter."}, status=status.HTTP_400_BAD_REQUEST)

        classrooms = Classroom.objects.filter(code__icontains=code_query)  # only active classrooms
        serializer = ClassroomSerializer(classrooms, many=True)
        return Response(serializer.data)
    
    
# ------------------------------
# Teacher Views
# ------------------------------
class TeacherClassroomViewSet(viewsets.ModelViewSet):
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get_queryset(self):
        teacher = Teacher.objects.get(user=self.request.user)
        return Classroom.objects.filter(teacher=teacher)

    def perform_create(self, serializer):
        teacher = Teacher.objects.get(user=self.request.user)
        serializer.save(teacher=teacher)
# This single ViewSet automatically handles all CRUD operations
# (list, retrieve, create, update, partial_update, destroy)


# ------------------------------
# Profile View (Read-only)
# ------------------------------
class ProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            student = Student.objects.get(user=request.user)
            serializer = StudentSerializer(student)
        except Student.DoesNotExist:
            teacher = Teacher.objects.get(user=request.user)
            serializer = TeacherSerializer(teacher)
        return Response(serializer.data)

class UpdateFCMTokenView(APIView):
    """
    Allows a logged-in Student or Teacher to update their Firebase Cloud Messaging (FCM) token.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        fcm_token = request.data.get('fcm_token')

        if not fcm_token:
            return Response(
                {"error": "FCM token is required."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user

        # Check if the logged-in user is a Student
        if hasattr(user, 'student'):
            user.student.fcm_token = fcm_token
            user.student.save()
            return Response({"message": "Student FCM token updated successfully!"}, status=status.HTTP_200_OK)
        
        # Check if the logged-in user is a Teacher
        elif hasattr(user, 'teacher'):
            user.teacher.fcm_token = fcm_token
            user.teacher.save()
            return Response({"message": "Teacher FCM token updated successfully!"}, status=status.HTTP_200_OK)
        
        # Fallback
        else:
            return Response({"error": "User profile not found."}, status=status.HTTP_404_NOT_FOUND)
        

class CreateAbsenceProposalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Get student object from logged-in user
        try:
            student = Student.objects.get(user=request.user)
        except Student.DoesNotExist:
            return Response({"error": "Student profile not found."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate required fields manually
        required_fields = ['reason_type', 'reason_description', 'start_datetime', 'end_datetime']
        missing_fields = [f for f in required_fields if not request.data.get(f)]
        if missing_fields:
            return Response({f: "This field is required." for f in missing_fields}, status=status.HTTP_400_BAD_REQUEST)

        # Create proposal with student from auth
        serializer = AbsenceProposalSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            proposal = serializer.save(student=student)  # assign student here

            # Update related AttendanceRecords to PENDING
            start_dt = serializer.validated_data['start_datetime']
            end_dt = serializer.validated_data['end_datetime']

            AttendanceRecord.objects.filter(
                student=student,
                timestamp__gte=start_dt,
                timestamp__lte=end_dt
            ).update(status="PENDING")

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        
        

class StudentAbsenceProposalListView(APIView):
    """
    List all absence proposals of the logged-in student, most recent first.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            student = Student.objects.get(user=request.user)
        except Student.DoesNotExist:
            return Response({"error": "Student profile not found."}, status=status.HTTP_400_BAD_REQUEST)

        proposals = AbsenceProposal.objects.filter(student=student).order_by('-timestamp')
        serializer = AbsenceProposalSerializer(proposals, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    
            
class TeacherPendingProposalsView(generics.ListAPIView):
    """
    Returns all pending absence proposals from students in classrooms taught by the logged-in teacher.
    """
    serializer_class = AbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Ensure user is a teacher
        teacher = getattr(self.request.user, "teacher", None)
        if not teacher:
            return AbsenceProposal.objects.none()

        # Get classrooms taught by this teacher
        classrooms = Classroom.objects.filter(teacher=teacher)

        # Return pending proposals from those classrooms
        return AbsenceProposal.objects.filter(
            student__enrollments__classroom__in=classrooms,
            status="PENDING"
        ).distinct()
        
        


class TeacherUpdateProposalView(generics.UpdateAPIView):
    """
    Teacher can approve or reject a student absence proposal.
    """
    queryset = AbsenceProposal.objects.all()
    serializer_class = AbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'  # pass proposal id in URL

    def patch(self, request, *args, **kwargs):
        proposal = self.get_object()
        teacher = getattr(request.user, "teacher", None)
        if not teacher:
            return Response({"detail": "Not authorized"}, status=status.HTTP_403_FORBIDDEN)

        # Ensure teacher owns the classroom(s) of the student
        student_classrooms = [enrollment.classroom for enrollment in proposal.student.enrollments.all()]
        if not any(c.teacher == teacher for c in student_classrooms):
            return Response({"detail": "Not authorized for this student"}, status=status.HTTP_403_FORBIDDEN)

        action = request.data.get("status")
        if action not in ["APPROVED", "REJECTED"]:
            return Response({"detail": "Invalid action, must be APPROVED or REJECTED"}, status=status.HTTP_400_BAD_REQUEST)

        # Update proposal status
        proposal.status = action
        proposal.save()

        # Update attendance records in the exact time range using timestamp
        records = AttendanceRecord.objects.filter(
            student=proposal.student,
            timestamp__gte=proposal.start_datetime,
            timestamp__lte=proposal.end_datetime
        )

        if action == "APPROVED":
            records.update(status="PRESENT")
        else:
            records.update(status="ABSENT")

        serializer = self.get_serializer(proposal)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==========================================
# GROUP ABSENCE PROPOSAL VIEWS
# ==========================================

# ------------------------------
# Student Views for Group Proposals
# ------------------------------

class CreateGroupAbsenceProposalView(generics.CreateAPIView):
    """Team Leader creates a new group proposal."""
    serializer_class = GroupAbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]


class JoinGroupAbsenceProposalView(APIView):
    """Normal student joins an existing group using ID and password."""
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def post(self, request):
        student = get_object_or_404(Student, user=request.user)
        group_id = request.data.get('group_id')
        password = request.data.get('join_password')

        if not group_id or not password:
            return Response({"error": "group_id and join_password are required"}, status=status.HTTP_400_BAD_REQUEST)

        proposal = get_object_or_404(GroupAbsenceProposal, id=group_id)

        if proposal.join_password != password:
            return Response({"error": "Invalid password"}, status=status.HTTP_403_FORBIDDEN)

        # Check if student is already in the group
        if GroupAbsenceParticipant.objects.filter(group_proposal=proposal, student=student).exists():
            return Response({"error": "You have already joined this group proposal."}, status=status.HTTP_400_BAD_REQUEST)

        # Attach student to the group
        GroupAbsenceParticipant.objects.create(group_proposal=proposal, student=student)
        return Response({"message": f"Successfully joined {proposal.title}"}, status=status.HTTP_200_OK)


class StudentGroupProposalHistoryView(generics.ListAPIView):
    """Shows all group proposals the logged-in student is a part of (Leader or Member)."""
    serializer_class = GroupAbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get_queryset(self):
        student = get_object_or_404(Student, user=self.request.user)
        # Fetch proposals where this student is linked as a participant
        return GroupAbsenceProposal.objects.filter(
            participants__student=student
        ).distinct().order_by('-timestamp')


# ------------------------------
# Teacher Views for Group Proposals
# ------------------------------

class TeacherPendingGroupProposalsView(generics.ListAPIView):
    """Shows pending group proposals containing students enrolled in the teacher's classes."""
    serializer_class = GroupAbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def get_queryset(self):
        teacher = get_object_or_404(Teacher, user=self.request.user)
        teacher_classrooms = Classroom.objects.filter(teacher=teacher)
        
        # Find group proposals that have participants enrolled in this teacher's classes
        return GroupAbsenceProposal.objects.filter(
            status="PENDING",
            participants__student__enrollments__classroom__in=teacher_classrooms
        ).distinct().order_by('-timestamp')


class TeacherUpdateGroupProposalView(APIView):
    """Teacher approves/rejects the group. Updates attendance for affected students."""
    permission_classes = [permissions.IsAuthenticated, IsTeacher]

    def patch(self, request, id):
        teacher = get_object_or_404(Teacher, user=request.user)
        proposal = get_object_or_404(GroupAbsenceProposal, id=id)

        action = request.data.get("status")
        if action not in ["APPROVED", "REJECTED"]:
            return Response({"detail": "Invalid action. Must be APPROVED or REJECTED"}, status=status.HTTP_400_BAD_REQUEST)

        # Find classrooms belonging to this teacher
        teacher_classrooms = Classroom.objects.filter(teacher=teacher)
        
        # Find participants in this proposal who belong to the teacher's classrooms
        participants = proposal.participants.filter(
            student__enrollments__classroom__in=teacher_classrooms
        )

        if not participants.exists():
            return Response({"detail": "No students in this group belong to your classes."}, status=status.HTTP_403_FORBIDDEN)

        # Update the main proposal status (for demo purposes, 1 teacher approval approves the group)
        proposal.status = action
        proposal.save()

        # Update the individual participant status
        participants.update(status=action)

        # Update the actual Attendance Records for these students during the event timeframe
        participant_students = [p.student for p in participants]
        
        records = AttendanceRecord.objects.filter(
            student__in=participant_students,
            classroom__in=teacher_classrooms,
            timestamp__gte=proposal.start_datetime,
            timestamp__lte=proposal.end_datetime
        )

        if action == "APPROVED":
            records.update(status="PRESENT")
        else:
            records.update(status="ABSENT")

        return Response({
            "message": f"Group proposal {action.lower()} successfully. Updated {records.count()} attendance records."
        }, status=status.HTTP_200_OK)
        
