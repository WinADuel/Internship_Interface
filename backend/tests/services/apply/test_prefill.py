from app.services.apply.prefill import _pick, prefill, saved_answer

PROFILE = {
    "first_name": "Dana",
    "last_name": "Lee",
    "preferred_name": "",
    "email": "dana@example.com",
    "phone": "206-555-0100",
    "city": "Seattle",
    "state": "WA",
    "country": "United States",
    "linkedin_url": "https://linkedin.com/in/dana",
    "github_url": "https://github.com/dana",
    "website_url": "",
    "current_company": "",
    "school": "University of Washington",
    "degree": "Bachelor's",
    "major": "Computer Engineering",
    "gpa": "3.8",
    "graduation_month": "June",
    "graduation_year": "2029",
    "work_authorized": "yes",
    "needs_sponsorship": "no",
    "willing_to_relocate": "yes",
    "how_heard": "LinkedIn",
    "pronouns": "",
    "gender": "decline",
    "race": "Asian",
    "hispanic_latino": "no",
    "veteran": "no",
    "disability": "decline",
    "lgbtq": "",
}

YES_NO = [{"label": "Yes", "value": "1"}, {"label": "No", "value": "0"}]


def field(key, label, kind="text", options=None, section="application"):
    return {"key": key, "label": label, "kind": kind, "options": options or [], "section": section, "required": False}


def opts(*labels):
    return [{"label": label, "value": label} for label in labels]


def test_standard_fields_fill_by_key_and_label():
    form = [
        field("first_name", "First Name"),
        field("last_name", "Last Name"),
        field("email", "Email"),
        field("q1", "LinkedIn Profile"),
        field("q2", "GitHub URL"),
        field("name", "Full name"),
        field("_systemfield_location", "Where do you plan on working from"),
        field("q3", "What university do you currently attend?"),
        field("q4", "Major / Discipline"),
        field("q5", "Expected graduation date"),
        field("q6", "Website"),  # blank in the profile: left empty
    ]
    answers = prefill(form, PROFILE, [], None)
    values = {k: v["value"] for k, v in answers.items()}
    assert values == {
        "first_name": "Dana",
        "last_name": "Lee",
        "email": "dana@example.com",
        "q1": "https://linkedin.com/in/dana",
        "q2": "https://github.com/dana",
        "name": "Dana Lee",
        "_systemfield_location": "Seattle, WA",
        "q3": "University of Washington",
        "q4": "Computer Engineering",
        "q5": "June 2029",
    }
    assert all(v["source"] == "profile" for v in answers.values())


def test_yes_no_questions_pick_the_option():
    form = [
        field("a", "Are you legally authorized to work in the United States?", "select", YES_NO),
        field("b", "Will you now or in the future require sponsorship for employment visa status?", "select", YES_NO),
        field("c", "Are you willing to relocate?", "boolean"),
        field("d", "Do you have 7 years of experience?", "boolean"),  # nothing in the profile
    ]
    values = {k: v["value"] for k, v in prefill(form, PROFILE, [], None).items()}
    assert values == {"a": "Yes", "b": "No", "c": "Yes"}


def test_demographic_answers_match_options_carefully():
    gender = opts("Male", "Female", "I don't wish to answer")
    race = opts("American Indian or Alaska Native", "I don't wish to answer", "Asian", "Black or African American", "Two or More Races")
    veteran = opts("I am not a protected veteran", "I identify as one or more of the classifications of a protected veteran", "I don't wish to answer")
    disability = opts("Yes, I have a disability, or have had one in the past", "No, I do not have a disability", "I don't wish to answer")
    form = [
        field("g", "Gender", "select", gender, "demographic"),
        field("r", "Race and Ethnicity", "select", race, "demographic"),
        field("v", "Veteran Status", "select", veteran, "demographic"),
        field("d", "Disability Status", "select", disability, "demographic"),
        field("l", "I consider myself a member of the LGBTQ+ community.", "select", opts("Yes", "No"), "demographic"),
    ]
    values = {k: v["value"] for k, v in prefill(form, PROFILE, [], None).items()}
    assert values == {
        "g": "I don't wish to answer",
        "r": "Asian",
        "v": "I am not a protected veteran",
        "d": "I don't wish to answer",
    }


def test_pick_never_confuses_male_and_female_or_guesses():
    options = opts("Female", "Male", "Decline to self-identify")
    assert _pick(options, "male") == "Male"
    assert _pick(options, "female") == "Female"
    assert _pick(options, "decline") == "Decline to self-identify"
    assert _pick(opts("Woman", "Man"), "decline") is None
    assert _pick(opts("Asian (Not Hispanic or Latino)", "White"), "Asian") == "Asian (Not Hispanic or Latino)"
    assert _pick(opts("East Asian", "South Asian"), "Asian") is None


def test_saved_answers_fill_matching_questions():
    saved = [
        {"question": "How did you hear about this job?", "answer": "Career fair"},
        {"question": "What has been your favorite project and why", "answer": "MicroMouse."},
    ]
    form = [
        field("q1", "How did you hear about this job?", "text"),
        field("q2", "What has been your favorite project or proudest accomplishment? Why?", "textarea"),
        field("q3", "What has been your favorite project, and why?", "textarea"),
    ]
    answers = prefill(form, {**PROFILE, "how_heard": ""}, saved, None)
    assert answers["q1"] == {"value": "Career fair", "source": "saved"}
    assert "q2" not in answers  # too different
    assert answers["q3"] == {"value": "MicroMouse.", "source": "saved"}


def test_saved_answer_needs_a_close_match():
    saved = [{"question": "Why do you want to work here?", "answer": "x"}]
    assert saved_answer("why do you want to work here", saved) == "x"
    assert saved_answer("Why?", saved) is None


def test_resume_upload_fills_with_the_file_name_only_when_there_is_one():
    form = [field("resume", "Resume/CV", "file"), field("cover_letter", "Cover Letter", "file")]
    assert prefill(form, PROFILE, [], "Dana-Lee-Resume.pdf") == {
        "resume": {"value": "Dana-Lee-Resume.pdf", "source": "profile"}
    }
    assert prefill(form, PROFILE, [], None) == {}


def test_multiselect_picks_each_listed_option():
    form = [field("m", "Race or Ethnicity (optional)", "multiselect", opts("East Asian", "South Asian", "White"), "demographic")]
    answers = prefill(form, {**PROFILE, "race": "East Asian; White"}, [], None)
    assert answers["m"]["value"] == ["East Asian", "White"]


def test_how_you_heard_is_matched_in_its_common_wordings():
    options = opts("Indeed", "LinkedIn", "Friend or Family")
    form = [
        field("a", "How did you hear about this job?"),
        field("b", "Please tell us how you heard about this opportunity.", "select", options),
    ]
    values = {k: v["value"] for k, v in prefill(form, PROFILE, [], None).items()}
    assert values == {"a": "LinkedIn", "b": "LinkedIn"}
