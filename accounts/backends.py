from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class ProfileBackend(ModelBackend):
    """Loads the signed-in user together with their profile.

    Every page needs `request.user.profile` (role, school, account gates), so
    fetching both in one query saves a database round trip on each request.
    """

    def get_user(self, user_id):
        UserModel = get_user_model()
        try:
            user = UserModel._default_manager.select_related('profile').get(pk=user_id)
        except UserModel.DoesNotExist:
            return None
        return user if self.user_can_authenticate(user) else None
