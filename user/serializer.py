import base64
from django.core.cache import cache

from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    AbsenceProposal, Student, Teacher, Classroom, Enrollment, AttendanceRecord,
    GroupAbsenceProposal, GroupAbsenceParticipant
)
from django.utils import timezone
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.serialization import load_der_public_key
from cryptography.exceptions import InvalidSignature

from user.utils.integrity import verify_play_integrity_token
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
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Student
        # ✅ Added 'public_key' to the fields list
        fields = ['id', 'username', 'password', 'uid', 'branch', 'fcm_token', 'public_key']

    # --- ADD THIS VALIDATION METHOD ---
    def validate_username(self, value):
        """
        Check if the username already exists in the User table.
        """
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value
    # ----------------------------------

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')

        user = User.objects.create_user(username=username, password=password)
        student = Student.objects.create(user=user, **validated_data)
        return student

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['username'] = instance.user.username
        return rep

class StudentTokenSerializer(TokenObtainPairSerializer):
    # Existing hardware signature field
    signature = serializers.CharField(write_only=True, allow_blank=True, required=False)
    
    # ✅ Catch the Play Integrity token from Flutter
    integrity_token = serializers.CharField(write_only=True, allow_blank=True, required=False)

    def validate(self, attrs):
        # 1. Standard Django Password Check
        data = super().validate(attrs)

        username = attrs.get(self.username_field)
        signature_hex = attrs.get("signature")
        integrity_token = attrs.get("integrity_token")

        # 2. Grab the challenge from RAM cache
        challenge = cache.get(f"login_challenge_{username}")
        
        # Start by assuming the device is completely safe
        device_status = "SECURE"

        if not challenge:
            raise serializers.ValidationError("Challenge expired. Please try again.")

        # ==========================================
        # 3. PLAY INTEGRITY CHECK (App/Software Verification)
        # ==========================================
        if integrity_token:
            # # ✅ LIVE: Calling the Google utility we wrote earlier!
            # from .utils.integrity import verify_play_integrity_token
            
            # Passing your exact package name
            is_genuine = verify_play_integrity_token(
                integrity_token, 
                package_name="com.piyush123abc.attendance_app"
            )
            
            if not is_genuine:
                print("❌ [DEBUG] Token is invalid or app is sideloaded!")
                device_status = "INTEGRITY_FAILED" 
        else:
            print("⚠️ [DEBUG] No Integrity Token provided. Skipping Play API check.")

        # ==========================================
        # 4. HARDWARE BINDING CHECK (Physical Device Verification)
        # ==========================================
        try:
            student = Student.objects.get(user=self.user)
            
            # If they didn't send a signature at all, instantly fail the binding
            if not signature_hex:
                raise Exception("Missing hardware signature")

            signature_bytes = bytes.fromhex(signature_hex)
            challenge_bytes = challenge.encode('utf-8')

            public_key_bytes = base64.b64decode(student.public_key)
            loaded_public_key = load_der_public_key(public_key_bytes)
            
            # Verify the math
            loaded_public_key.verify(signature_bytes, challenge_bytes, ECDSA(SHA256()))

            # Only delete the challenge if it successfully passes!
            cache.delete(f"login_challenge_{username}")

        except (Student.DoesNotExist, InvalidSignature, Exception) as e:
            print(f"⚠️ [DEBUG] Hardware Binding Failed: {e}")
            # If this fails AND integrity failed, we prioritize showing the Hardware warning, 
            # or you can handle it however you want in Flutter. Here we overwrite the status.
            device_status = "BINDING_FAILED"

        # 5. Inject the final status into the JWT response for Flutter
        data['device_status'] = device_status
        return data
# ---------------------------
# Teacher Serializer (handles user creation)
# ---------------------------
class TeacherSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True)

    class Meta:
        model = Teacher
        # ✅ Added 'fcm_token' to the fields list
        fields = ['id', 'username', 'password', 'uid', 'department', 'fcm_token']

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')
        user = User.objects.create_user(username=username, password=password)
        # **validated_data will handle saving the fcm_token
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