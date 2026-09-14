from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('teacher', 'Teacher'),
        ('registrar', 'Registrar'),
        ('schoolhead', 'School Head'),
        ('admin', 'Admin'),
    ]
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='teacher')
    deped_email = models.EmailField(blank=True, null=True)
    school_id = models.CharField(max_length=50, blank=True, null=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.role}"

# Auto-create a profile when a User is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()