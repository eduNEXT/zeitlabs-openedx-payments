"""edx-platform models mocks for testing purposes."""

from django.contrib.auth import get_user_model
from django.db import models
from opaque_keys.edx.django.models import CourseKeyField


class CourseOverview(models.Model):
    """Mock"""
    id = CourseKeyField(db_index=True, primary_key=True, max_length=255)  # pylint: disable=invalid-name
    org = models.CharField(max_length=255, db_collation='NOCASE')
    catalog_visibility = models.TextField(null=True)
    start = models.DateTimeField(null=True)
    end = models.DateTimeField(null=True)
    display_name = models.TextField(null=True)
    enrollment_start = models.DateTimeField(null=True)
    enrollment_end = models.DateTimeField(null=True)
    self_paced = models.BooleanField(default=False)
    course_image_url = models.TextField()
    visible_to_staff_only = models.BooleanField(default=False)
    effort = models.TextField(null=True)
    max_student_enrollments_allowed = models.IntegerField(null=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'course_overviews_courseoverview'


class CourseMode(models.Model):
    """Mock"""
    course = models.ForeignKey(
        CourseOverview,
        db_constraint=False,
        db_index=True,
        related_name='modes',
        on_delete=models.DO_NOTHING,
    )
    mode_slug = models.CharField(max_length=100, verbose_name=('Mode'))
    mode_display_name = models.CharField(max_length=255, verbose_name=('Display Name'))
    min_price = models.IntegerField(default=0, verbose_name=('Price'))
    currency = models.CharField(default='usd', max_length=8)
    _expiration_datetime = models.DateTimeField(
        default=None, null=True, blank=True,
        verbose_name=('Upgrade Deadline'),
        db_column='expiration_datetime',
    )
    expiration_datetime_is_explicit = models.BooleanField(
        default=False,
        verbose_name=('Lock upgrade deadline date'),
    )
    sku = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name='SKU',
    )

    HONOR = 'honor'
    VERIFIED = 'verified'
    AUDIT = 'audit'
    NO_ID_PROFESSIONAL_MODE = 'no-id-professional'
    AUDIT_MODES = [AUDIT, HONOR, 'unpaid-executive-education', 'unpaid-bootcamp']

    class Meta:
        app_label = 'fake_models'
        db_table = 'course_modes_coursemode'
        unique_together = ('course', 'mode_slug', 'currency')

    @property
    def expiration_datetime(self):
        """Mock"""
        return self._expiration_datetime

    @classmethod
    def is_mode_upgradeable(cls, mode_slug):
        """Mock: whether a learner enrolled in the mode can upgrade to another."""
        return mode_slug in cls.AUDIT_MODES


class CourseEnrollmentManager(models.Manager):
    def is_course_full(self, course):
        """Mock"""
        return False


class CourseEnrollment(models.Model):
    """Mock"""
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE)
    course = models.ForeignKey(CourseOverview, on_delete=models.CASCADE)
    is_active = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)
    mode = models.CharField(default=CourseMode.AUDIT, max_length=100)

    objects = CourseEnrollmentManager()

    class Meta:
        app_label = 'fake_models'
        db_table = 'student_courseenrollment'

    @classmethod
    def enroll(cls, user, course_key, mode=None, check_access=False, can_upgrade=False, enterprise_uuid=None):
        cls.objects.get_or_create(
            user=user,
            course_id=course_key,
            defaults={
                'mode': mode or CourseMode.AUDIT,
                'is_active': True
            }
        )

    @classmethod
    def is_enrollment_closed(cls, user, course):
        """Mock"""
        return

    @classmethod
    def is_enrolled(cls, user, course_key):
        """Mock"""
        return cls.objects.filter(user=user, course__id=course_key, is_active=True).exists()

    @classmethod
    def get_enrollment(cls, user, course_key):
        """Mock: the user's enrolment in the course, or None."""
        return cls.objects.filter(user=user, course__id=course_key).first()

    def update_enrollment(self, mode=None, is_active=None, skip_refund=False, enterprise_uuid=None):
        """Mock: change the enrolment's mode and activity."""
        if mode is not None:
            self.mode = mode
        if is_active is not None:
            self.is_active = is_active
        self.save()

    @classmethod
    def enrollment_mode_for_user(cls, user, course_id):
        """Mock: the mode and the activity of the user's enrolment in the course, or (None, None) without one."""
        enrollment = cls.objects.filter(user=user, course__id=course_id).first()
        if enrollment is None:
            return None, None
        return enrollment.mode, enrollment.is_active


class UserRetirementRequest(models.Model):
    """Mock"""
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)

    class Meta:
        app_label = 'fake_models'
        db_table = 'user_api_userretirementrequest'

    @classmethod
    def has_user_requested_retirement(cls, user):
        """Mock"""
        return cls.objects.filter(user=user).exists()


class UserProfile(models.Model):
    """Mock"""
    user = models.OneToOneField(get_user_model(), related_name='profile', on_delete=models.CASCADE)
    name = models.CharField(blank=True, max_length=255, db_index=True)

    class Meta:
        app_label = 'fake_models'
        db_table = 'auth_userprofile'
