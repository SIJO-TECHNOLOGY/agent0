# Design

## Design Goal

The UI should feel like a quiet internal productivity tool for SIJO business managers.

It should be:

- Clear
- Lightweight
- Professional
- Candidate-search focused
- Fast to scan

It should not feel like:

- A marketing landing page
- A generic AI playground
- A generic BoondManager console
- A dashboard overloaded with widgets

## Visual Language

The current V1 design uses:

- Light blue background
- White surfaces
- Soft borders
- Compact cards
- Rounded corners around 8px
- Inter font
- SIJO blue accents

Keep this direction.

## Logo Usage

The logo is stored at:

```txt
assets/logo.png
```

Current placements:

- Login screen
- Loading screen
- Sidebar
- Empty chat state

Sizing principles:

- Use natural proportions.
- Use `height`-based sizing.
- Keep `width: auto`.
- Avoid large logo containers.
- Do not stretch the image.

## Chat Design

User messages:

- Right aligned
- Blue bubble
- Compact label

Assistant messages:

- Left aligned
- White bubble
- Soft border
- Compact label

Structured candidate responses should appear below the assistant message inside the chat flow.

## Candidate Cards

Candidate cards should be visually distinct from normal chat bubbles.

Cards should show:

- Identity
- Match score
- Experience
- Location
- Availability
- Summary
- Skills
- Actions

Cards should remain compact and readable.

## Candidate Detail

Candidate detail is displayed as a structured card in the chat flow.

It is not a generic detail renderer. It is candidate-specific.

## Technical Summary

Technical summary is displayed as a structured analysis card.

It should be easy to scan:

- Summary first
- Strengths
- Weaknesses
- Languages
- Tools and levels

## Clarification Form

Clarification forms appear inline in the chat.

They should be small and focused:

- One title
- One input per backend question
- One submit button

## Candidate Drawer

The drawer is used from candidate cards for quick profile inspection.

It should remain:

- Right aligned on desktop
- Full width on mobile
- Focused on candidate information

## Responsive Behavior

Mobile should preserve:

- Readable messages
- Full-width candidate cards
- Full-width drawer
- No overlapping text
- No stretched logo

Avoid adding layout complexity unless the POC requires it.

