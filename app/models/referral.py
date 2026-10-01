from enum import Enum


class ReferralSource(str, Enum):
    """Options for the "How did you hear about us?" dropdown."""
    GOOGLE_SEARCH = "google_search"
    SOCIAL_MEDIA = "social_media"
    LINKEDIN = "linkedin"
    FRIEND_OR_COLLEAGUE = "friend_or_colleague"
    BLOG_OR_ARTICLE = "blog_or_article"
    EVENT_OR_WEBINAR = "event_or_webinar"
    OTHER = "other"