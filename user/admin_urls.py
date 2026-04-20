# user/admin_urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .admin_views import (
    GodModeStudentViewSet, 
    GodModeTeacherViewSet, 
    GodModeClassroomViewSet, 
    GodModeEnrollmentViewSet,
    GodModeAttendanceViewSet,
    GodModeAbsenceProposalViewSet,
    GodModeGroupAbsenceProposalViewSet,
    GodModeSecurityAnomalyViewSet
)

router = DefaultRouter()
router.register(r'students', GodModeStudentViewSet, basename='admin-student')
router.register(r'teachers', GodModeTeacherViewSet, basename='admin-teacher')
router.register(r'classrooms', GodModeClassroomViewSet, basename='admin-classroom')
router.register(r'enrollments', GodModeEnrollmentViewSet, basename='admin-enrollment')
router.register(r'attendance', GodModeAttendanceViewSet, basename='admin-attendance')
router.register(r'absence-proposals', GodModeAbsenceProposalViewSet, basename='admin-absence')
router.register(r'group-proposals', GodModeGroupAbsenceProposalViewSet, basename='admin-group-absence')
router.register(r'anomalies', GodModeSecurityAnomalyViewSet, basename='admin-anomaly')

urlpatterns = [
    # This automatically creates all routes under the router
    path('', include(router.urls)),
]