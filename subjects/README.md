# Subjects

Every `*.json` file in this folder is one subject. The file name is the subject's id
(lowercase letters, digits, `-` and `_`), e.g. `my-subject.json`. New or edited files show up
immediately - no restart needed. You can also create and edit them on the **Admin -> Subjects** page.

This folder ships empty on purpose; the `*.json` files you add are ignored by git (see `.gitignore`).

```json
{
  "title": "Subject title",
  "description": "Optional short text shown on the subject page.",
  "cards": [
    {
      "id": "card-1",
      "type": "choice",
      "question": "Example multiple-choice question?",
      "options": [
        { "text": "The right answer", "correct": true },
        { "text": "A wrong answer" },
        { "text": "Another wrong answer" }
      ],
      "explanation": "Optional. Shown together with the right answer."
    },
    {
      "id": "card-2",
      "type": "open",
      "question": "Example open question?",
      "answer": "The model answer you compare yourself against."
    }
  ]
}
```

Rules

- `id` of each card is **required**, must be unique inside the subject and should never change
  afterwards - comments and flags are attached to it. Allowed: letters, digits, `-`, `_`.
- `type` is `"choice"` (multiple choice, graded automatically) or `"open"` (you compare your
  answer with the model answer and mark yourself). If you leave `type` out, it is `"choice"` when
  the card has `options`, otherwise `"open"`.
- Choice cards need at least 2 options and at least one with `"correct": true`. More than one
  correct option = "select all that apply".
- `explanation` is optional.
- A broken file is hidden from students until it is fixed; the Admin page shows what is wrong.
