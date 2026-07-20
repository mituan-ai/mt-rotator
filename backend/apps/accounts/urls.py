from django.urls import path

from .views import (
    CsrfView,
    InvitationImportView,
    InvitationListCreateView,
    InvitationReissueView,
    InvitationRevokeView,
    InviteInspectView,
    LoginView,
    LogoutView,
    MeView,
    PasswordChangeView,
    RegisterView,
    UserListView,
    UserRevokeSessionsView,
    UserStatusView,
)

urlpatterns = [
    path("csrf", CsrfView.as_view()),
    path("invitations/inspect", InviteInspectView.as_view()),
    path("register", RegisterView.as_view()),
    path("login", LoginView.as_view()),
    path("logout", LogoutView.as_view()),
    path("me", MeView.as_view()),
    path("password/change", PasswordChangeView.as_view()),
    path("admin/invitations", InvitationListCreateView.as_view()),
    path("admin/invitations/import", InvitationImportView.as_view()),
    path("admin/invitations/<uuid:invitation_id>/revoke", InvitationRevokeView.as_view()),
    path("admin/invitations/<uuid:invitation_id>/reissue", InvitationReissueView.as_view()),
    path("admin/users", UserListView.as_view()),
    path("admin/users/<uuid:user_id>", UserStatusView.as_view()),
    path("admin/users/<uuid:user_id>/sessions/revoke", UserRevokeSessionsView.as_view()),
]
