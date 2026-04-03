# attendance_session/urls.py
from django.urls import path
from .views import (
    FrontendAnomalyReportView,
    GetSessionCredentialsView,
    GetTeacherGPSView,
    GetTeacherSessionCredentialsView,
    SetTeacherGPSView,
    StartSessionView,
    PassTokenView,
    AddExceptionView,
    GetExceptionListView,
    MarkExceptionPresentView,
    FinalizeSessionView,
    ActiveSessionsView,
    ClassroomSessionStatusView,
    AddMasterNodeView,
    RemoveMasterNodeView,
    ListMasterNodesView
)
#path('session/', include('attendance_session.urls')),
urlpatterns = [
    # ---------------------------
    # Teacher-only endpoints
    # ---------------------------
    # Start attendance session for a classroom
    path('teacher/classroom/<int:classroom_id>/start/', StartSessionView.as_view(), name='start-session'),

    # Get current exception list for classroom
    path('teacher/classroom/<int:classroom_id>/exceptions/', GetExceptionListView.as_view(), name='get-exception-list'),

    # Mark students present (from exception or otherwise)
    path('teacher/classroom/<int:classroom_id>/mark-present/', MarkExceptionPresentView.as_view(), name='mark-present'),

    # Finalize attendance session
    path('teacher/classroom/<int:classroom_id>/finalize/', FinalizeSessionView.as_view(), name='finalize-session'),

    # List all active sessions
    path('teacher/sessions/active/', ActiveSessionsView.as_view(), name='active-sessions'),
    
    # NEW: Get session credentials for the teacher to act as a receiver
    path('teacher/classroom/<int:classroom_id>/credentials/', GetTeacherSessionCredentialsView.as_view(), name='teacher-session-credentials'),
    
    # post gps coordintes
    path('classroom/<int:classroom_id>/teacher/gps/', SetTeacherGPSView.as_view(), name='set_teacher_gps'),

    # ---------------------------
    # Student-only endpoints
    # ---------------------------
    # Pass token to another student
    path('student/classroom/<int:classroom_id>/pass-token/', PassTokenView.as_view(), name='pass-token'),

    # Add self to exception list
    path('student/classroom/<int:classroom_id>/exception/', AddExceptionView.as_view(), name='add-exception'),
    
    #check activeness of the session for a classromm
    path("student/classroom/<int:classroom_id>/session/",ClassroomSessionStatusView.as_view(),name="classroom-session-status"),
    
    #check if the classroom has an active session
    path('session/status/<int:classroom_id>/', ClassroomSessionStatusView.as_view(), name='classroom-session-status'),
    
    #get all the session keys
    path('classroom/<int:classroom_id>/credentials/', GetSessionCredentialsView.as_view(), name='get_session_credentials'),
    
    # Master Node endpoints
    path('teacher/classroom/<int:classroom_id>/master-node/add/', AddMasterNodeView.as_view(), name='add-master-node'),
    path('teacher/classroom/<int:classroom_id>/master-node/remove/', RemoveMasterNodeView.as_view(), name='remove-master-node'),
    path('teacher/classroom/<int:classroom_id>/master-node/list/', ListMasterNodesView.as_view(), name='list-master-nodes'),
    
    
    # get coordinates gps
    path('classroom/<int:classroom_id>/student/gps/', GetTeacherGPSView.as_view(), name='get_teacher_gps'),
    
    #security anamoly
    # Route for the Flutter App (JWT / Session Token required in headers)
    path('security/student-report/', FrontendAnomalyReportView.as_view(), name='student-anomaly-report'),
]


