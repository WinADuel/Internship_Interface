import { describe, expect, it } from "vitest";
import { canAutoApply } from "./boards";

describe("canAutoApply", () => {
  it.each([
    "https://job-boards.greenhouse.io/discord/jobs/8917177002",
    "https://boards.greenhouse.io/stripe/jobs/123?gh_src=x",
    "https://boards.greenhouse.io/embed/job_app?for=acme&token=55",
    "https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd",
    "https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd/apply",
    "https://jobs.ashbyhq.com/ramp/34413f8d-26bf-4bbc-8ade-eb309a0e2245/application",
  ])("accepts %s", (url) => expect(canAutoApply(url)).toBe(true));

  it.each([
    "https://careers.google.com/jobs/1",
    "https://acme.wd5.myworkdayjobs.com/careers/job/Intern_R1",
    "https://jobs.lever.co/palantir",
    "javascript:alert(1)",
    "not a url",
  ])("refuses %s", (url) => expect(canAutoApply(url)).toBe(false));
});
