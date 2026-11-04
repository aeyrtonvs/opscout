---
name: summary
description: Writes a short summary of this session's work, ready to paste into a ticket, a chat message or a postmortem, in the user's configured write-up formats. Use when the user asks for a summary, a write-up, a ticket update, a message for the team or a postmortem of what was done.
argument-hint: "[format]"
allowed-tools: Bash(opscout writeup formats *)
---

# Summary

## Contract

- **Deliverable:** one block of plain text in the requested write-up format, inside a single
  fenced `text` block so it can be copied as is, followed by one line naming the format used.
- **Constraints:** only facts stated in this session; the format's sections in order and its
  line limit; the language the formats name, or else the language the user writes in; every
  rule below.
- **Non-goals:** never list what was evaluated and ruled out, nor how the result was reached;
  never invent ticket keys, names, times or figures; never include a secret value; never
  post, send or save the write-up, and never call a tool.
- **Acceptance:** someone who was not in the session understands what happened, why, what was
  done and what is pending, in the format's shape and within its limit.

## The formats

!`opscout writeup formats --config "${user_config.config_dir}"`

## Procedure

1. **Check the formats.** If the text above says the configuration has problems, write no
   summary. Tell the user that their configuration has problems and to run
   `opscout config validate`, then stop.
2. **Pick the format**: the one named in "$ARGUMENTS" or in the user's request, matched by
   name or meaning (a "chat message" is `message`). With none named, use `ticket`. If the
   named format is not listed above, list the formats above in one line, ask which one to
   use, and write nothing else.
3. **Gather the facts** from this session only: what happened, why, what was done, what is
   pending, and what the format's sections ask for. Leave out every hypothesis, check or
   option that was considered and ruled out, and the steps taken to reach the result. A
   first guess that turned out to be the cause is a fact; keep it. If a secret value appeared
   in the session, leave the value out; you may say that the secret exists and where.
4. **If there is nothing to summarize** (no work was done in this session), say so in one
   sentence and ask what the summary should cover. Write no block.
5. **Write the block.** Put each section heading on its own line, in the format's order,
   followed by its text. A section with nothing to say gets a few words ("Nothing pending."),
   never invented work. Without sections, write free text. Count every non-empty line inside
   the block, headings included, and stay within the format's limit: cut detail, never
   facts the reader needs. Follow the rules for every format and the format's own rules.
6. **Close** with one line after the block: `Format: <name>`, then, if none was named, the
   other formats listed above; and if the formats above say none were found in the
   configuration, add that the built-in formats were used and why.

Never call a tool while doing this: everything needed is in this session and above.
