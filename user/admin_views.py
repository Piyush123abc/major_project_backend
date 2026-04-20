# user/admin_views.py
from rest_framework import viewsets, permissions
from rest_framework.response import Response
from django.db.models import Count, Q
from rest_framework.decorators import action
from user.models import (
    Student, Teacher, Classroom, Enrollment, AttendanceRecord,
    AbsenceProposal, GroupAbsenceProposal, GroupAbsenceParticipant
)
from attendance_session.models import SecurityAnomaly

# Import your existing serializers
from user.serializer import (
    StudentSerializer, TeacherSerializer, ClassroomSerializer, 
    EnrollmentSerializer, AttendanceRecordSerializer, 
    AbsenceProposalSerializer, GroupAbsenceProposalSerializer,
    GroupAbsenceParticipantSerializer
)
from user.permission import IsSuperUser 

# (Quick inline serializer since SecurityAnomaly is in a different app)
from rest_framework import serializers
class SecurityAnomalyAdminSerializer(serializers.ModelSerializer):
    student_uid = serializers.CharField(source='student.uid', read_only=True)
    student_name = serializers.CharField(source='student.user.username', read_only=True)
    anomaly_type_display = serializers.CharField(source='get_anomaly_type_display', read_only=True)

    class Meta:
        model = SecurityAnomaly
        fields = '__all__'

# -----------------------------------------------------
# GOD-MODE CRUD ENDPOINTS (For React Admin Dashboard)
# -----------------------------------------------------

class GodModeStudentViewSet(viewsets.ModelViewSet):
    queryset = Student.objects.all().order_by('-id')
    serializer_class = StudentSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    # 🌟 NEW: Student Attendance History Endpoint
    @action(detail=True, methods=['get'])
    def attendance(self, request, pk=None):
        student = self.get_object()
        
        # Grab all attendance records for this student, newest first
        records = AttendanceRecord.objects.filter(student=student).select_related('classroom').order_by('-date', '-timestamp')
        
        total_classes = records.count()
        present_count = records.filter(status='PRESENT').count()
        absent_count = records.filter(status='ABSENT').count()
        
        history = [{
            "id": r.id,
            "date": r.date.strftime("%Y-%m-%d") if r.date else "Unknown",
            "status": r.status,
            "classroom_code": r.classroom.code,
            "classroom_name": r.classroom.name
        } for r in records]

        return Response({
            "student_name": student.user.username,
            "uid": student.uid,
            "stats": {
                "total": total_classes,
                "present": present_count,
                "absent": absent_count,
                # Avoid division by zero
                "attendance_percentage": round((present_count / total_classes * 100)) if total_classes > 0 else 0
            },
            "history": history
        })

class GodModeTeacherViewSet(viewsets.ModelViewSet):
    queryset = Teacher.objects.all().order_by('-id')
    serializer_class = TeacherSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        teacher = self.get_object()
        
        # Group attendance records by Classroom and Date to create "Historical Sessions"
        sessions_data = AttendanceRecord.objects.filter(classroom__teacher=teacher).values(
            'classroom__id',
            'classroom__code',
            'classroom__name',
            'date'
        ).annotate(
            total_present=Count('id', filter=Q(status='PRESENT')),
            total_absent=Count('id', filter=Q(status='ABSENT')),
            total_students=Count('id')
        ).order_by('-date', '-classroom__id')[:20]  # Grab the last 20 sessions

        formatted_sessions = []
        for session in sessions_data:
            formatted_sessions.append({
                "classroom_id": session['classroom__id'],
                "classroom_code": session['classroom__code'],
                "classroom_name": session['classroom__name'],
                "date": session['date'].strftime("%Y-%m-%d") if session['date'] else "Unknown",
                "present": session['total_present'],
                "absent": session['total_absent'],
                "total": session['total_students']
            })

        return Response({
            "teacher_name": teacher.user.username,
            "recent_sessions": formatted_sessions
        })

class GodModeClassroomViewSet(viewsets.ModelViewSet):
    queryset = Classroom.objects.all().order_by('-created_at')
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

class GodModeEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = Enrollment.objects.all().order_by('-enrolled_at')
    serializer_class = EnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

class GodModeAttendanceViewSet(viewsets.ModelViewSet):
    queryset = AttendanceRecord.objects.all().order_by('-timestamp')
    serializer_class = AttendanceRecordSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

class GodModeAbsenceProposalViewSet(viewsets.ModelViewSet):
    queryset = AbsenceProposal.objects.all().order_by('-timestamp')
    serializer_class = AbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

class GodModeGroupAbsenceProposalViewSet(viewsets.ModelViewSet):
    queryset = GroupAbsenceProposal.objects.all().order_by('-timestamp')
    serializer_class = GroupAbsenceProposalSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]

class GodModeSecurityAnomalyViewSet(viewsets.ModelViewSet):
    queryset = SecurityAnomaly.objects.all().order_by('-timestamp')
    serializer_class = SecurityAnomalyAdminSerializer
    permission_classes = [permissions.IsAuthenticated, IsSuperUser]