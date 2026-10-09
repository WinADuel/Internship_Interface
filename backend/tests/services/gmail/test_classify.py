import pytest

from app.models.interview import InterviewKind
from app.services.gmail.classify import SuggestionKind, classify, interview_round_kind

K = SuggestionKind

CASES = [
    # --- offers
    ("Your offer from Stripe", "Hi Dana, we're pleased to offer you the Software Engineering Intern role", K.OFFER),
    ("Offer Letter - Summer 2027 Internship", "Please find attached your offer letter. Kindly sign by", K.OFFER),
    ("Congratulations!", "We would like to extend you an offer for the Data Science Intern position", K.OFFER),
    ("Next steps", "We are excited to extend an offer of employment. Your recruiter will share next steps", K.OFFER),
    # --- rejections
    ("Your application to Rivian", "Thank you for applying. Unfortunately, we have decided to move forward with other candidates", K.REJECTION),
    ("Update on your candidacy", "After careful review we will not be moving forward with your application at this time", K.REJECTION),
    ("Stripe application update", "We've decided not to proceed with your candidacy for this role", K.REJECTION),
    ("Re: Software Intern", "Thanks for your interest. You are no longer under consideration for this position", K.REJECTION),
    ("Thank you", "We’re moving forward with other applicants whose experience more closely matches", K.REJECTION),
    ("Application status", "Thank you for interviewing with us. We won't be moving forward. We'll keep your resume for future interview opportunities", K.REJECTION),
    ("UNFORTUNATELY", "", K.REJECTION),
    # Rejection outranks the confirmation phrase it usually contains.
    ("Thank you for your application", "Unfortunately the position has been filled", K.REJECTION),
    # --- interviews
    ("Interview invitation - Rivian", "We'd like to invite you to interview for the Software Intern role", K.INTERVIEW),
    ("Next steps with Ramp", "Could you share your availability for a 30 minute call next week?", K.INTERVIEW),
    ("Quick chat?", "I'd love to schedule a call to talk about the internship", K.INTERVIEW),
    ("Book your interview", "Please pick a time on my calendly.com/jane-recruiter page", K.INTERVIEW),
    ("Scheduling", "Use this link to book: https://app.goodtime.io/schedule/abc", K.INTERVIEW),
    ("Notion - next steps", "We were impressed with your application and want to talk about next steps.", K.INTERVIEW),
    ("Your Stripe interviews", "Here is the agenda for your onsite interviews on Thursday", K.INTERVIEW),
    ("Phone screen", "Please use our scheduling link to choose a slot for your technical interview", K.INTERVIEW),
    # Rescheduling is not a rejection.
    ("Interview reschedule", "Unfortunately your interviewer is out sick; we need to reschedule your interview. Please send your availability", K.INTERVIEW),
    # Strong cues win over an assessment mention.
    ("After your HackerRank", "Thanks for completing the HackerRank! We'd like to schedule an interview", K.INTERVIEW),
    # A confirmation that says it may lead to an interview is a confirmation.
    ("Thank you for applying to Stripe", "We'll review your application and if you're selected for an interview, a recruiter will reach out.", K.CONFIRMATION),
    ("Application received", "Should your background match, we will contact you to arrange an interview. Thanks!", K.CONFIRMATION),
    ("Thanks for applying!", "Next steps: our team reviews every application within two weeks.", K.CONFIRMATION),
    # --- assessments (the interview process mention doesn't make it an interview)
    ("Stripe Online Assessment", "Please complete the online assessment within 7 days", K.ASSESSMENT),
    ("Your CodeSignal invitation", "Rivian has invited you to take a CodeSignal General Coding Assessment as the next step in our interview process", K.ASSESSMENT),
    ("Coding challenge", "As the next step, please complete this HackerRank challenge before your interview", K.ASSESSMENT),
    ("Take-home exercise", "Attached is the take-home project for the data intern role", K.ASSESSMENT),
    ("Codility test", "You have been invited to a Codility test", K.ASSESSMENT),
    ("Next steps", "Please complete the coding challenge linked below", K.ASSESSMENT),
    # --- confirmations
    ("Thank you for applying to Rivian", "We have received your application for Software Engineering Intern", K.CONFIRMATION),
    ("Application Received - Data Science Intern", "", K.CONFIRMATION),
    ("Thanks for your interest in Ramp", "Our team will review your application.", K.CONFIRMATION),
    ("Your application has been submitted", "", K.CONFIRMATION),
    ("Stripe", "Thank you for your application to the Summer 2027 internship", K.CONFIRMATION),
    # --- nothing job-related
    ("Your weekly summary", "You have 3 new followers", None),
    ("Verify your email", "Click below to verify your candidate account", None),
    ("", "", None),
    # Whole words only.
    ("Interviewer training", "Thanks for volunteering as an interviewer", None),
    ("Offered courses", "The offerings for Spring are out", None),
    ("Fortunately all good", "The package arrived", None),
]


@pytest.mark.parametrize(("subject", "snippet", "expected"), CASES)
def test_classify(subject, snippet, expected):
    assert classify(subject, snippet) == expected


@pytest.mark.parametrize(
    ("subject", "snippet", "expected"),
    [
        ("Phone screen with Rivian", "A recruiter will call you", InterviewKind.RECRUITER_SCREEN),
        ("Recruiter call", "Share your availability", InterviewKind.RECRUITER_SCREEN),
        ("Technical interview", "A 60 minute coding session", InterviewKind.TECHNICAL),
        ("Technical phone screen", "", InterviewKind.TECHNICAL),
        ("Coding interview", "", InterviewKind.TECHNICAL),
        ("Final round", "Meet the team on site", InterviewKind.OTHER),
    ],
)
def test_interview_round_kind(subject, snippet, expected):
    assert interview_round_kind(subject, snippet) == expected
