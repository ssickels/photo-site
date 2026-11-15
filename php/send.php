<?php
/**
 * send.php: the contact form's handler, at /contact/send.php.
 *
 * config.php sits next to it and is written by the build from site.yaml
 * (contact:) and the private site.local.yaml (mail_to, turnstile_secret). It
 * only returns an array, so requesting it in a browser shows nothing.
 *
 * The page (contact.js) posts with ajax=1 and gets JSON back, so a visitor's
 * message stays in the form if something goes wrong. Without JavaScript the
 * form posts normally and is redirected back to /contact/?status=...
 */

require __DIR__ . '/contact-lib.php';

contact_init(require __DIR__ . '/config.php');

list($name, $email, $message, $captcha) = contact_gate();

$sent = contact_send($name, $email, $message, [
    'Site'    => (string) contact_opt('site_label'),
    'Captcha' => $captcha,
]);

if ($sent) {
    contact_respond('success');
}
contact_respond(
    'error',
    'The message could not be sent just now. Please try again shortly.',
    'send'
);
