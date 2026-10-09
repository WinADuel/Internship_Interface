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
    # Common rejections that open with a confirmation phrase (review fix).
    ("Thank you for your interest in Stripe", "Thank you for your interest in Stripe. We have decided not to move forward with your application", K.REJECTION),
    ("Your application to Rivian", "We regret to inform you that we will not be proceeding with your application at this time", K.REJECTION),
    ("Thank you for applying", "After careful consideration we have decided to move forward with candidates whose experience more closely aligns with the role", K.REJECTION),
    ("Re: Data Science Intern", "Thank you for your application. We are unable to offer you a position at this time", K.REJECTION),
    ("Update from Notion", "Thank you for applying. You have not been selected for the next round of our process", K.REJECTION),
    ("Ramp application update", "Thanks for your interest in Ramp. We will not be progressing your application further", K.REJECTION),
    ("Your application", "Thank you for applying. On this occasion your application was unsuccessful", K.REJECTION),
    ("Software Engineering Intern", "We wanted to let you know that the position has been filled. We appreciate your interest", K.REJECTION),
    ("Thank you from Figma", "We have chosen to proceed with other applicants for this internship", K.REJECTION),
    ("Re: Summer internship", "Thanks for interviewing. We've decided to go with another candidate whose background is a closer fit", K.REJECTION),
    ("Stripe interview update", "Thank you for your time. We are not in a position to extend an offer for this role", K.REJECTION),
    ("Thank you for applying", "We regret that we are not able to move forward with your candidacy", K.REJECTION),
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
    # Confirmations promise interviews in general; only a strong cue counts.
    ("Thank you for applying to Rivian", "We have received your application. Selected candidates will be contacted for an interview.", K.CONFIRMATION),
    ("Application received", "Thank you for applying! If your profile is a fit we will reach out to you to schedule interviews.", K.CONFIRMATION),
    ("Thanks for your interest in Ramp", "Our recruiting team will review your application and we will reach out to qualified candidates to schedule interviews", K.CONFIRMATION),
    ("Thank you for your application", "Shortlisted applicants will be invited to interview in November.", K.CONFIRMATION),
    ("Thank you for applying to Stripe", "Due to the volume of applications we will only contact candidates whose qualifications match the role", K.CONFIRMATION),
    ("Thank you for applying!", "If we decide not to move forward, we will let you know by email.", K.CONFIRMATION),
    ("Thanks for applying to Figma", "Interviews for this role begin in January; we review every application.", K.CONFIRMATION),
    # ... and a strong cue in a confirmation is still an invitation.
    ("Thank you for applying to Notion", "We'd like to invite you to interview. Please share your availability for next week", K.INTERVIEW),
    ("Thanks for your interest in Ramp", "We'd love to schedule a call with you; pick a time at calendly.com/ramp-recruiting", K.INTERVIEW),
    ("Thank you for your application", "I would like to schedule a time with you to talk about the internship", K.INTERVIEW),
    ("Thanks for applying to Rivian", "We were impressed and would like to schedule a 30 minute phone screen", K.INTERVIEW),
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
    # A refused offer is a rejection, not an offer.
    ("Offer update", "We are unable to extend an offer to you at this time", K.REJECTION),
    ("Your application", "Unfortunately we cannot offer you the internship this season", K.REJECTION),
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
