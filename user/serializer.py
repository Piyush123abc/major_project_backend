from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    AbsenceProposal, Student, Teacher, Classroom, Enrollment, AttendanceRecord,
    GroupAbsenceProposal, GroupAbsenceParticipant
)
from django.utils import timezone

# ---------------------------
# User Serializer (read-only)
# ---------------------------
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

# ---------------------------
# Student Serializer (handles user creation & profile read)
# ---------------------------
class StudentSerializer(serializers.ModelSerializer):
    # Write-only for creation
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)
    auth_key = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Student
        fields = ['id', 'username', 'password', 'uid', 'branch', 'auth_key']

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')
        auth_key = validated_data.pop('auth_key', None)  # optional

        user = User.objects.create_user(username=username, password=password)
        student = Student.objects.create(user=user, auth_key=auth_key, **validated_data)
        return student

    def to_representation(self, instance):
        """Return username from related User in profile GET"""
        rep = super().to_representation(instance)
        rep['username'] = instance.user.username  # override username key
        return rep
    
# ---------------------------
# Teacher Serializer (handles user creation)
# ---------------------------
class TeacherSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Teacher
        fields = ['id', 'username', 'password', 'uid', 'department']

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')
        user = User.objects.create_user(username=username, password=password)
        teacher = Teacher.objects.create(user=user, **validated_data)
        return teacher


# ---------------------------
# Classroom Serializer
# ---------------------------
class ClassroomSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.user.username", read_only=True)

    class Meta:
        model = Classroom
        fields = ["id", "name", "code", "teacher_name", "created_at", "active"]


# ---------------------------
# Enrollment Serializer (student auto from login)
# ---------------------------
class EnrollmentSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Enrollment
        fields = ['id', 'student', 'classroom', 'enrolled_at']

    def create(self, validated_data):
        # Get student from logged-in user
        request = self.context.get('request')
        student = Student.objects.get(user=request.user)

        # Remove 'student' if accidentally present in validated_data
        validated_data.pop('student', None)

        return Enrollment.objects.create(student=student, **validated_data)


# ---------------------------
# Attendance Record Serializer (student auto from login)
# ---------------------------

class AttendanceRecordSerializer(serializers.ModelSerializer):
    student = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ['id', 'student', 'classroom', 'date', 'status', 'timestamp']

    def create(self, validated_data):
        request = self.context.get('request')
        student = Student.objects.get(user=request.user)

        # Default date to today if not provided
        if 'date' not in validated_data:
            validated_data['date'] = timezone.now().date()

        return AttendanceRecord.objects.create(student=student, **validated_data)
    
    
    

class AbsenceProposalSerializer(serializers.ModelSerializer):
    # Nested student info for GET, PK input for POST/PUT
    student = StudentSerializer(read_only=True)
    student_id = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(), source='student', write_only=True, required=False
    )

    # Provide full URL to the uploaded document
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = AbsenceProposal
        fields = [
            'id',
            'student',
            'student_id',  # write-only for assigning student
            'reason_type',
            'reason_description',
            'document',
            'document_url',
            'start_datetime',
            'end_datetime',
            'status',  # editable
            'timestamp',
        ]
        read_only_fields = ['timestamp']

    def get_document_url(self, obj):
        if obj.document:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.document.url)
            return obj.document.url
        return None

    def create(self, validated_data):
        # Handle optional student assignment from request if not provided
        if 'student' not in validated_data:
            request = self.context.get('request')
            if request and hasattr(request.user, 'student'):
                validated_data['student'] = request.user.student
        return AbsenceProposal.objects.create(**validated_data)

    def update(self, instance, validated_data):
        # Allow updating status, reason, dates, description, document
        return super().update(instance, validated_data)
    
# ---------------------------
# Group Absence Proposal Serializers
# ---------------------------

class GroupAbsenceParticipantSerializer(serializers.ModelSerializer):
    """Read-only serializer to display participant details inside the group proposal."""
    student_uid = serializers.CharField(source='student.uid', read_only=True)
    student_name = serializers.CharField(source='student.user.username', read_only=True)

    class Meta:
        model = GroupAbsenceParticipant
        fields = ['id', 'student_uid', 'student_name', 'status']

class GroupAbsenceProposalSerializer(serializers.ModelSerializer):
    # This displays the participants when reading the data
    participants = GroupAbsenceParticipantSerializer(source='participants.all', many=True, read_only=True)
    leader_name = serializers.CharField(source='created_by.user.username', read_only=True)
    
    # Provide full URL to the uploaded document
    document_url = serializers.SerializerMethodField()

    class Meta:
        model = GroupAbsenceProposal
        fields = [
            'id', 'title', 'reason_type', 'reason_description', 
            'document', 'document_url', 'start_datetime', 'end_datetime', 
            'status', 'timestamp', 'participants', 'join_password', 'leader_name'
        ]
        read_only_fields = ['status', 'timestamp', 'created_by']
        extra_kwargs = {
            # Make the password write-only so it isn't exposed in API responses
            'join_password': {'write_only': True} 
        }

    def get_document_url(self, obj):
        if obj.document:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.document.url)
            return obj.document.url
        return None

    def create(self, validated_data):
        # 1. Assign the logged-in student as the 'created_by' leader
        request = self.context.get('request')
        leader_student = None
        
        if request and hasattr(request.user, 'student'):
            leader_student = request.user.student
            validated_data['created_by'] = leader_student
        
        # 2. Create the main Group Proposal 
        # (join_password and all other fields are automatically saved here)
        proposal = GroupAbsenceProposal.objects.create(**validated_data)
        
        # 3. Automatically attach the Team Leader as the first participant
        if leader_student:
            GroupAbsenceParticipant.objects.create(
                group_proposal=proposal,
                student=leader_student
            )
                
        return proposal