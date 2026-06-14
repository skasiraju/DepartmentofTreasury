# TTB Label Verifier — Design and Approach

## What this is

TTB Label Verifier is a small web tool that checks an alcohol beverage label against the data that was filed for it. You upload a photo of the label, type in the details from the application (brand, alcohol content, net contents, and so on), and the tool reads the label and tells you, field by field, whether the two agree — and separately, whether the mandatory government health warning is present and worded correctly.

It's a prototype, not a production system. The goal was to take the routine part of a compliance agent's job — sitting with an application on one screen and the label artwork on another, checking that the numbers line up — and see how much of that a vision model can do reliably, and how fast.

## The problem, in the stakeholders' words

A few things from the interview notes shaped the whole design:

Sarah (Deputy Director) said most of the review work is "literally just making sure the number on the form is the same as the number on the label," and that speed is non-negotiable — the last scanning vendor took 30–40 seconds per label and the agents abandoned it. Anything slower than about five seconds won't get used. She also wanted something her 73-year-old mother could operate: clean, obvious, no hunting for buttons.

Jenny (Junior Agent) pointed out that the warning check is trickier than it sounds. It has to be exact — word for word — and the "GOVERNMENT WARNING:" part has to be in capitals. People try to get creative with smaller fonts or reworded text, and that's an automatic rejection.

Dave (28-year veteran) made the case for judgment over blind pattern-matching: "STONE'S THROW" on the label and "Stone's Throw" on the form are obviously the same thing, and a tool that flags that as a mismatch just makes his life harder.

So the brief, distilled: read the label accurately, decide the warning strictly but the ordinary fields forgivingly, return an answer in a few seconds, and keep the screen simple.

## How it works

The app does two distinct jobs, and I deliberately kept them apart:

1. **Read the label.** The photo goes to OpenAI's vision model, which returns the label's fields as structured JSON.
2. **Judge the result.** Plain Python compares those fields against the application data and applies the compliance rules.

The reason for the split is trust. The model is good at reading messy photos but I don't want it deciding what "compliant" means — that should be explicit, written down in code, and testable. So the model never sees the application data and never returns a pass/fail. It only transcribes what it can see. Every approve/reject decision lives in one file (`verifier.py`) that a person can read and a test can pin down.

The stack is intentionally boring: a FastAPI backend, a single HTML page with vanilla JavaScript for the front end (no build step, nothing to learn), Pillow for image handling, and the OpenAI Python SDK for the model call. Boring is a feature here — there's very little to break, and the whole thing runs with one command.

### Reading the label

The extractor sends the image to `gpt-4o` and asks for a fixed set of fields back as JSON: brand name, class/type, alcohol content, net contents, bottler/producer, country of origin, and the full government warning. The prompt tells it to copy text exactly as printed and, importantly, to return `null` for anything it can't actually read rather than guessing. (More on why that instruction matters in the testing section — I learned it the hard way.)

Two small touches make a real difference on phone photos:

- **Downscaling.** The source images are 12-megapixel (4000×3000). A label doesn't need that, and big images are slower and more expensive to send, so every image is shrunk to 1280px on its longest side before it goes out. This is most of what keeps the response under the five-second target.
- **Orientation.** Phone photos carry a rotation tag that not every library honors. The app applies it, so a picture taken sideways arrives the right way up.

The model call runs at temperature 0 for repeatability — the same label should give the same reading twice — and the output is constrained to a JSON object, so there's no fragile text parsing on our side.

### Checking against the application

"The application" is the form on the left side of the page. In the real TTB workflow that's the COLA filing — the values the producer declared. This prototype doesn't connect to COLA (that's a separate system with its own authorization story), so the declared values are entered by hand. They're the source of truth; the label is checked against them.

Ordinary fields use a forgiving comparison: case-insensitive, with surrounding and repeated whitespace ignored. That's what lets "STONE'S THROW" match "Stone's Throw," exactly the situation Dave described. If a field is missing from the label, or simply doesn't match, it's marked as a fail with both the expected and found values shown side by side, so the agent can see why.

The government warning is held to a higher standard, because the regulation is. Three checks have to pass:

1. The warning must be present at all.
2. The phrase **GOVERNMENT WARNING:** must appear in capital letters — a common rejection reason and one of the few things TTB is explicit about.
3. The rest of the statement must match the wording in 27 CFR Part 16 word for word.

There's one subtlety I had to get right. Plenty of real labels print the entire warning in capitals — Captain Morgan does, for instance — and that is perfectly compliant. An early version of the check compared the body against mixed-case reference text and so would have wrongly rejected every all-caps warning. The check now requires the heading to be uppercase but compares the wording case-insensitively, which matches how the rule actually works. Whitespace is normalized too, so a stray double space doesn't trip it.

## Decisions and trade-offs

**OpenAI versus a local model.** I went with OpenAI's hosted vision model for accuracy and because it needs no GPU to run. The honest caveat is that IT mentioned their network blocks outbound traffic to ML endpoints — which is almost certainly why an earlier version of this project used a local model. For a prototype that's fine; for their environment the realistic path is Azure OpenAI (they're already on Azure), which gives the same model while keeping the traffic inside their tenant. I've noted that in the recommendations rather than pretending the firewall isn't there.

**Abstain instead of guess.** For a compliance tool, a confident wrong answer is worse than a blank. A blank sends the field to a human; a wrong value might get waved through. The prompt and the design both lean toward returning `null` when the label can't be read, and the verifier treats a blank as a fail-to-be-reviewed rather than a silent pass.

**Rules in code, not in the model.** Covered above, but it's the single most important decision in the design. It's why the compliance logic has unit tests and the warning rule reads like the regulation.

## How I tested it

Two layers.

The verification rules have a unit test suite (`tests/test_verifier.py`, 18 tests) that runs with no network and no model — it feeds known field dictionaries straight into the verifier and checks the pass/fail logic: exact matches pass, a wrong ABV fails, a lowercase warning heading fails, a truncated warning fails, an all-caps warning passes, the case-difference example passes, and so on. These are fast and they pin the behavior so it can't quietly drift.

For the reading itself, there's no answer key — these are real photographs of real bottles, not generated labels with known content. So I wrote a harness (`tests/run_extraction_test.py`) that pulls a random sample of images from the provided set, runs each through the real extractor, and saves both the model's output and the exact (downscaled) image it saw into an `_eval/` folder. Then I graded the results by eye, image against extraction.

I ran it on 30 randomly sampled photos. The results:

- **Speed:** about 2.1 seconds per label on average, 29 of 30 within the five-second target.
- **Cost:** roughly half a cent per label on `gpt-4o` (around 14 cents for all 30).
- **Accuracy:** 202 of 210 fields correct, about 96%. Bottler and country of origin were perfect across the sample; the weakest field was alcohol content, almost always on shots where the ABV genuinely wasn't legible.
- **Government warning:** detected on every one of the 26 labels that actually showed a warning, and correctly left blank on the 4 photos that were front or marketing panels with no warning. The wording came back verbatim — including, on one tequila bottle, faithfully preserving a real defect where the label omits the word "THE." That's exactly the kind of thing the exact-match check exists to catch.

The test also caught a mistake of my own. My first prompt included example values like "45% Alc./Vol. (90 Proof)" and "750 mL" to show the expected format. On a couple of unreadable, glary labels the model copied those examples instead of admitting it couldn't read the field — so it confidently reported the wrong volume on a bottle that was clearly 1.75 litres. I removed the concrete examples and told it to return `null` when it can't read something. Re-running the same 30 images, that fixed the cases that were outright wrong and turned the rest into honest blanks. It's a good illustration of why the testing was worth doing: the bug was invisible until it was put in front of real photos.

## Where it's strong and where it struggles

The warning handling is the strongest part, which is the right thing to be strong at — it's both the legal must-have and the field people try to cheat. Reading of printed fields on a reasonably clear panel (the Bravium and Worthy wines, the Gekkeikan sake) is essentially perfect, ABV and net contents included.

The struggles are honest and mostly physical:

- A single photo usually shows one side of the bottle, so fields on the other side come back blank. That's correct behavior, not an error, but it means verifying a real submission properly needs a front and a back image.
- When only the back is in frame, the model sometimes reports the producer or distillery as the brand, because the brand front isn't visible.
- Very small text near the bottom of a label (a tiny "750ML") is occasionally missed.

None of these are guessing problems anymore; they're "the information isn't legible in this particular photo" problems, which is the honest failure mode to have.

## Assumptions I made

- One label image per check, supplied by the user, in JPEG/PNG/WebP.
- The application data is entered by hand; there's no COLA integration.
- US labels and the US federal government warning — beverage-specific and state-specific rules are out of scope for the prototype.
- Nothing is stored. It's stateless, which keeps it simple and sidesteps the PII and retention questions that a real deployment would have to answer.
- "Brand name" on a back-only photo may legitimately be ambiguous.

## What I'd do next

- **Front and back images** per submission, to close most of the "field came back blank" gaps.
- **Batch uploads.** The extractor is already asynchronous, so accepting many images and running them concurrently is a natural extension — and it directly answers the request from the Seattle office to stop processing big importer filings one at a time.
- **Azure OpenAI**, behind Private Link, as the production-realistic way past the firewall while keeping data in their tenant.
- **Surface "needs review" explicitly.** A blank field should be shown as something the model wasn't sure about, so an agent's attention lands exactly there, rather than being treated as a plain miss.
- **Model cost at scale.** `gpt-4o` is a sensible default. At 150,000 labels a year it would still be a few hundred dollars, but it's worth A/B testing the smaller, cheaper model on the easy, clean labels and reserving the larger one for the hard cases.
- **Typography is a known gap.** The warning rules also require bold text at a minimum size. From transcribed text alone we can check wording and the capital heading but not boldness or font size; that would need layout analysis of the image.


## Tools used

Python 3, FastAPI and Uvicorn for the web layer, the OpenAI Python SDK (the `gpt-4o` vision model) for reading the label, Pillow for image resizing and orientation, Pydantic for the request/response models, a single hand-written HTML/CSS/JavaScript page for the interface, and pytest for the rule tests.
