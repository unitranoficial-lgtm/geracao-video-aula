# Validate Flow authentication inside the project

- Date: 2026-09-29
- Workflow: Google Flow automation
- Observation: The authenticated Flow project UI may load successfully while the root URL redirects to `/about`. Authentication checks that only look for the home-page “New project” button produce false logout errors.
- Improvement applied: validate a known project URL when a project ID exists, and accept authenticated project navigation labels such as “Todas as mídias” and “Vídeos”. The setup flow also follows the landing CTA and account chooser before waiting for manual password/2FA.
- Result: the saved session reopened the project without another login and the script listed/downloaded the generated cards normally.
