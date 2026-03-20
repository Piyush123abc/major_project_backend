from django.db import models
from django.contrib.auth.models import User
import os
from django.utils import timezone

class Student(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    uid = models.CharField(max_length=20, unique=True)  # College UID
    branch = models.CharField(max_length=50)            # e.g., CSE, ECE
    auth_key = models.TextField(null=True, blank=True)  # Biometric public key

    def __str__(self):
        return f"{self.user.username} ({self.uid}, {self.branch})"


class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    uid = models.CharField(max_length=20, unique=True)  # College UID
    department = models.CharField(max_length=50)        # e.g., CSE, ECE

    def __str__(self):
        return f"{self.user.username} ({self.uid}, {self.department})"

class Classroom(models.Model):
    name = models.CharField(max_length=100)   # e.g., "Database Management Systems"
    code = models.CharField(max_length=20, unique=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="classrooms")
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)  # True if attendance session is active

    def __str__(self):
        return f"{self.code} - {self.name}"

class Enrollment(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="enrollments")
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="enrollments")
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'classroom')

    def __str__(self):
        return f"{self.student.user.username} → {self.classroom.code}"




class AttendanceRecord(models.Model):
    STATUS_CHOICES = (
        ("PRESENT", "Present"),
        ("ABSENT", "Absent"),
        ("LATE", "Late"),
        ("PENDING", "Pending"), 
    )

    student = models.ForeignKey("Student", on_delete=models.CASCADE, related_name="attendance_records")
    classroom = models.ForeignKey("Classroom", on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="PRESENT")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Remove unique_together to allow multiple records per day
        ordering = ['date', 'timestamp']

    def __str__(self):
        return f"{self.student.user.username} | {self.classroom.code} |  {self.timestamp} | {self.status}"
    
    
def absence_document_upload_path(instance, filename):
    """
    File will be uploaded to:
    media/absence_proposals/student_<id>/YYYYMMDD_HHMMSS_filename.ext
    """
    import os
    from django.utils import timezone

    base, ext = os.path.splitext(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    unique_filename = f"{timestamp}_{base}{ext}"
    return f'absence_proposals/student_{instance.student.id}/{unique_filename}'

class AbsenceProposal(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    REASON_CHOICES = (
        ("MEDICAL", "Medical"),
        ("EVENT", "Event"),
        ("ACADEMIC", "academic"),
        ("OTHER", "Other"),
    )

    student = models.ForeignKey(
        "Student",
        on_delete=models.CASCADE,
        related_name="absence_proposals"
    )
    reason_type = models.CharField(max_length=20, choices=REASON_CHOICES)
    reason_description = models.TextField(blank=True, null=True)
    document = models.FileField(
        upload_to=absence_document_upload_path,
        blank=True,
        null=True
    )
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.student.user.username} | {self.reason_type} | {self.status}"
    
    
def group_absence_document_upload_path(instance, filename):
    """
    File will be uploaded to:
    media/group_absence_proposals/leader_<id>/YYYYMMDD_HHMMSS_filename.ext
    """
    import os
    from django.utils import timezone

    base, ext = os.path.splitext(filename)
    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
    unique_filename = f"{timestamp}_{base}{ext}"
    return f'group_absence_proposals/leader_{instance.created_by.id}/{unique_filename}'


class GroupAbsenceProposal(models.Model):
    """The main group event/leave created by a team leader."""
    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    REASON_CHOICES = (
        ("MEDICAL", "Medical"),
        ("EVENT", "Event"),
        ("ACADEMIC", "Academic"),
        ("SPORTS", "Sports"), # Added sports as it's common for groups
        ("OTHER", "Other"),
    )

    title = models.CharField(max_length=200) # e.g., "Smart India Hackathon Finals"
    created_by = models.ForeignKey(
        "Student", 
        on_delete=models.CASCADE, 
        related_name="created_group_proposals"
    ) # The student who submitted the form
    
# Added a default value so migrations run smoothly without prompting
    join_password = models.CharField(max_length=50, default='1234')
    
    reason_type = models.CharField(max_length=20, choices=REASON_CHOICES)
    reason_description = models.TextField(blank=True, null=True)
    
    # Document is NOT compulsory (blank=True, null=True)
    document = models.FileField(
        upload_to=group_absence_document_upload_path,
        blank=True,
        null=True
    )
    
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    
    # Overall status of the entire group event
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.title} (Leader: {self.created_by.user.username}) | {self.status}"


class GroupAbsenceParticipant(models.Model):
    """The individual 'solo proposal' connecting a student to a group event."""
    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    group_proposal = models.ForeignKey(
        GroupAbsenceProposal, 
        on_delete=models.CASCADE, 
        related_name="participants"
    )
    student = models.ForeignKey(
        "Student", 
        on_delete=models.CASCADE, 
        related_name="group_participations"
    )
    
    # Individual status (in case 1 student is rejected but the rest of the group is approved)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    class Meta:
        # A student can only be added to a specific group proposal once
        unique_together = ('group_proposal', 'student')

    def __str__(self):
        return f"{self.student.user.username} -> {self.group_proposal.title} | {self.status}"