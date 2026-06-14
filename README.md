# TTB Label Verifier

A small web app that checks an alcohol beverage label against the data from its
COLA application — the same brand-name / ABV / net-contents / government-warning
check a TTB agent does by eye, but with the reading done by a vision model.

You upload a photo of the label, type in (or paste) the details from the
application, and the app tells you field-by-field whether the label matches and
whether the mandatory government warning is present and correct.

## How it works

There are two steps, and they're deliberately kept separate:

1. **Extraction** (`app/services/extractor.py`) — the label photo is sent to
   OpenAI's vision model, which returns the label's fields as JSON (brand,
   class/type, alcohol content, net contents, bottler, country of origin, and
   the full government warning). This is the part that "reads" the label.

2. **Verification** (`app/services/verifier.py`) — plain Python compares each
   extracted field against the application data. Brand/ABV/etc. use a forgiving
   comparison (case- and whitespace-insensitive, so `STONE'S THROW` matches
   `Stone's Throw`). The government warning is held to a stricter standard: the
   `GOVERNMENT WARNING:` heading must be in caps, and the wording must match the
   statement in 27 CFR Part 16 word-for-word.

Keeping the AI strictly to reading, and leaving the pass/fail decision to code,
means the compliance rules are explicit, testable, and don't drift.

### What "the application" is

In the real TTB workflow an agent opens an application (the COLA filing) and
checks the label artwork against what the producer declared. This app models
that as the form on the left of the page — brand name, class/type, alcohol
content, net contents, bottler, and optional country of origin. Those declared
values are the source of truth; the label is checked against them. There's no
COLA integration (out of scope for a prototype), so the application data is
entered by hand or, in the test harness, generated as dummy records.

## Setup

Requires Python 3.10+ and an OpenAI API key.

```bash
python -m venv .venv
.venv\Scripts\activate        # on Windows; use source .venv/bin/activate elsewhere
pip install -r requirements.txt
```

Create a `.env` file in the project root with:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o            # optional; gpt-4o is the default
```

## How well does it work?

Tested on 30 random photos from the provided set (`--seed 42`). These are real
phone photos — back labels, odd angles, glare, low contrast, a few shot
upside-down — so they're a fair stress test, not clean studio shots.

- **Speed:** ~2.1 s per label on average (median 2.0 s, p95 ~3.1 s). 29 of 30
  came back within the 5-second target Sarah called out. Helped by downscaling
  every image to 1280 px before sending — labels don't need 12 megapixels.
- **Cost:** about half a cent per label on `gpt-4o` (~$0.14 for all 30).
- **Accuracy:** by my own field-by-field review against the images, **202 of 210
  fields correct (~96%)**. Perfect on bottler and country of origin; the weakest
  field was alcohol content (~90%), almost entirely on labels where the ABV
  wasn't legible in the shot.
- **Government warning** (the field that matters most): detected on every one of
  the 26 labels that actually showed a warning, and correctly left blank on the
  4 photos that were front/marketing panels with no warning. Wording came back
  verbatim, including faithfully preserving a real defect on one bottle whose
  warning omits the word "THE" — exactly the kind of thing the exact-match check
  exists to catch.

One useful thing the test surfaced: an early version of the prompt included
example values (`45% Alc./Vol. (90 Proof)`, `750 mL`), and on a couple of
unreadable labels the model copied those examples instead of admitting it
couldn't read the field. The prompt now omits concrete examples and tells the
model to return `null` rather than guess, which turned those confident-wrong
answers into honest blanks.

## Assumptions & limitations

- **One photo, one panel.** A single photo usually shows only the front or the
  back, so fields on the other side come back blank. That's correct behavior,
  but it means full verification of a real submission needs front and back
  images. The app handles one image at a time today.
- **Can't judge typography.** The warning rules also require bold text at a
  minimum font size. From extracted text alone we can check wording and the
  caps heading, but not boldness or size — that would need layout analysis.
- **Brand on back labels.** When a photo only shows the back, the model
  sometimes reports the producer/distillery as the brand, since the brand front
  isn't in frame.
- **No persistence / no auth.** Nothing is stored; it's a stateless prototype,
  in line with "don't do anything crazy" for the proof of concept.

## Recommendations

- **Mind the firewall — consider Azure OpenAI.** Marcus mentioned the network
  blocks outbound traffic to ML endpoints, which is likely why the original
  build ran a local model. The public OpenAI API will hit that same wall in
  their environment. Since they're already on Azure, **Azure OpenAI** would give
  the same models while keeping traffic inside their tenant and compliance
  boundary — the most production-realistic path. Keeping a local-model fallback
  is also reasonable.
- **Batch uploads.** The extractor is already async; wiring the front end and an
  endpoint to accept many images and run them concurrently would directly answer
  Janet's 200-at-once request.
- **Ask for front + back.** Two photos per submission would close most of the
  "field came back blank" gaps.
- **Surface "couldn't read this" explicitly.** A blank field should be shown as
  *needs review*, not silently treated as missing, so an agent's eye lands on
  exactly the spots the model wasn't sure about.
- **Model cost at scale.** `gpt-4o` is a good default for accuracy. At 150k
  labels a year, it's worth A/B testing `gpt-4o-mini` for the easy, clean labels
  and reserving the larger model for the ones it's unsure about.
