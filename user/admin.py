from django.contrib import admin
from .models import AbsenceProposal, GroupAbsenceParticipant, GroupAbsenceProposal, Student, Teacher, Classroom, Enrollment, AttendanceRecord

admin.site.register(Student)
admin.site.register(Teacher)
admin.site.register(Classroom)
admin.site.register(Enrollment)
admin.site.register(AttendanceRecord)
admin.site.register(AbsenceProposal)

admin.site.register(GroupAbsenceProposal)
admin.site.register(GroupAbsenceParticipant)
