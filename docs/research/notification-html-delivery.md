# Custom HTML notification delivery: Knock and Novu

Research date: 2026-11-08

## Summary

Neither Knock nor Novu treats arbitrary HTML as something that must be parsed
to discover a semantic notification title and body. Both separate the trigger
payload from the channel-specific output that a workflow step renders. Their
email contracts retain a distinct subject, while HTML is the message body.
Novu explicitly permits HTML in email and in-app body fields. Knock's documented
in-app API exposes typed content blocks rather than a general raw-HTML message
body.

This suggests Tiber should keep authored HTML as a body representation, not
parse it into semantic text. Tiber's `NotificationContent` now carries
`plain_text_body` and `html_body` alongside the explicit `title`. This supports
HTML-only delivery and multipart email without inferring the subject from
markup.

## Knock

### Sending is workflow-triggered

Knock's trigger API takes a workflow key, recipients, and optional `data`.
Knock runs those values through the workflow; the `data` map is for values
required by workflow templates, not a direct channel message body.
[Triggering workflows via the API](https://docs.knock.app/send-notifications/triggering-workflows/api)

Knock says templates represent message content for a channel step and are
managed through workflow modification; its Management API does not expose
standalone template CRUD. It does expose a template-preview endpoint that can
render inline template content without first persisting it.
[Templates Management API](https://docs.knock.app/mapi-reference/templates)

### Email keeps subject, HTML, and optional text distinct

Knock's email template schema requires `subject` and either `html_body` or
`visual_blocks`. `text_body` is optional and, when omitted, Knock documents
that it can be generated from the HTML or visual blocks. The API preview example
returns the rendered `subject`, `html_body`, and `text_body` separately.
[Email template schema](https://docs.knock.app/mapi-reference/templates/schemas/email_template)
[Template preview](https://docs.knock.app/mapi-reference/templates)

This is not HTML-to-semantic-content extraction: the subject is still explicit,
and HTML remains its own body representation.

### In-app content is structured

Knock's in-app feed response represents generated message content as typed
blocks, including markdown, text, and button sets. A markdown block exposes
rendered HTML, while a text block exposes rendered plaintext. The cited
contract does not describe accepting arbitrary HTML as an in-app body.
[In-app APIs and real-time service](https://docs.knock.app/in-app-ui/api-overview)

## Novu

### Sending is workflow-triggered

Novu describes its trigger-event API as the way to send notifications. A trigger
identifies the workflow and recipients; its payload passes custom data for
workflow rendering and routing rather than defining a direct message body.
[Trigger event API](https://docs.novu.co/api-reference/events/trigger-event)

### Email supports custom HTML without deriving its subject

Novu's email template documentation supports custom HTML through its code
editor or API and says Novu compiles the HTML/Liquid template using payload and
subscriber context. In Novu Framework's email step, `subject` is required and
`body` is required; the body may be plain text or HTML.
[Writing email templates](https://docs.novu.co/platform/integrations/email/writing-email-template)
[Email step](https://docs.novu.co/framework/typescript/steps/email)

The HTML body is therefore a first-class rendered body value, not a source from
which Novu must infer the email subject.

### In-app HTML is opt-in and remains body/subject data

Novu Framework's in-app step requires a `body` string and allows an optional
`subject`. Novu's Inbox documentation says these fields are sanitized by
default. To render HTML, a workflow must disable content sanitization and the
client must use the corresponding HTML render hook. Novu warns that opting out
of sanitization can create XSS risk.
[In-App step](https://docs.novu.co/framework/typescript/steps/inApp)
[HTML in Notifications](https://docs.novu.co/platform/inbox/advanced-customization/html-in-notifications)

Again, the contract does not parse HTML to construct semantic content: HTML is
the field's value, and subject/body remain separate.

## Implications for Tiber

1. Keep the request source choice clear: a template reference or direct
   `content`. The content value can carry plain text, HTML, or both.
2. Do not scrape arbitrary HTML for a title or text body. HTML structure and
   semantics are client-controlled, and extraction would be lossy and
   unpredictable.
3. Keep the email subject explicit in `title`; do not infer it from tags such
   as `<title>` or `<h1>`.
4. Preserve both body representations through intake, persistence, API
   responses, and provider calls. Text-only channels use `plain_text_body`;
   email/in-app can use `html_body`. Reject HTML-only content for channels that
   cannot deliver HTML. When both forms are provided, plain text is available
   as the fallback for those channels.
5. In-app HTML requires an explicit display contract. If a future dashboard
   renders it, decide whether Tiber sanitizes it or requires a trusted-source
   opt-out, and ensure the client uses a sandboxed/otherwise safe renderer.
   Novu's documented behavior illustrates the tradeoff; it is not evidence that
   unsanitized HTML is safe.

These are design implications from the cited contracts, not a claim that either
vendor exposes the same content model Tiber uses. Both
vendors primarily expose workflow-triggered delivery rather than a single
direct-send endpoint with these fields.
