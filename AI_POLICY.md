# AI Usage Policy

MorgenMCP is written with substantial AI assistance, and AI tools are welcome
here. The rules below exist so that assistance stays reviewable — not to
discourage it.

- **All AI usage in any form must be disclosed.** State the tool you used
  (e.g. Claude Code, Cursor, Amp) along with the extent that the work was
  AI-assisted. Put it in the pull request description, and mark AI-assisted
  commits with MorgenMCP's `Assisted-by:` trailer, inspired by the
  [Linux kernel's guidance](https://docs.kernel.org/process/coding-assistants.html):

  ```
  Assisted-by: LLM (Claude Code, claude-opus-5)
  ```

  The description tells a reviewer what to look at; the trailer stays in
  `git log` after the pull request thread is forgotten.

  Do **not** use `Co-Authored-By` for an AI tool. It asserts authorship, which
  carries responsibilities a tool cannot hold — and GitHub counts those
  identities as project contributors. Authorship and sign-off remain entirely
  yours. Do not paste links to AI chat transcripts either: they are typically
  private, often contain credentials or account data, and are worthless to
  anyone who cannot open them.

- **The human-in-the-loop must fully understand all code.** If you can't
  explain what your changes do and how they interact with the greater system
  without the aid of AI tools, do not contribute to this project.

- **Issues and discussions can use AI assistance but must have a full
  human-in-the-loop.** Any content generated with AI must have been reviewed
  _and edited_ by a human before submission. AI is very good at being overly
  verbose and including noise that distracts from the main point. Humans must
  do their research and trim this down.

- **No AI-generated media is allowed (art, images, videos, audio, etc.).**
  Text and code are the only acceptable AI-generated content, per the other
  rules in this policy.

- **Verify claims against this repository before filing them.** An agent's
  confident description of the code is not evidence. Run it. This applies to
  bug reports especially: state the command you ran, the interpreter version,
  and the actual output.

## There are Humans Here

Please remember that this project is maintained by humans.

Every discussion, issue, and pull request is read and reviewed by humans. It is
a boundary point at which people interact with each other and the work done. It
is rude and disrespectful to approach this boundary with low-effort, unqualified
work, since it puts the burden of validation on the maintainer.

In a perfect world, AI would produce high-quality, accurate work every time. But
today, that reality depends on the driver of the AI.

## AI is Welcome Here

**The reason for a strict AI policy is not an anti-AI stance.** Much of this
repository was written with AI assistance, and that is expected to continue.
The policy exists because unreviewed AI output shifts the cost of verification
onto whoever reads it next, and that cost is real whether or not the output
happens to be correct.

Disclosure is not a confession. It is context that helps a reviewer know where
to look.

---

## Attribution

This policy is adapted from the
[Ghostty project's AI policy](https://github.com/ghostty-org/ghostty/blob/main/AI_POLICY.md),
used under the MIT License:

> MIT License
>
> Copyright (c) 2024 Mitchell Hashimoto, Ghostty contributors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Notable changes include dropping the public denouncement list and the
maintainer-exemption clause (both presuppose a maintainer team and an external
contributor base this project does not yet have), and adding a clause on
verifying claims against the repository.
