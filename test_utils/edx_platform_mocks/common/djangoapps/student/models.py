"""edX Mock"""

from fake_models.classes import (  # pylint: disable=unused-import
    AlreadyEnrolledError,
    CourseEnrollmentException,
    CourseFullError,
    EnrollmentClosedError,
    NonExistentCourseError,
)
from fake_models.models import CourseEnrollment, UserProfile  # pylint: disable=unused-import
