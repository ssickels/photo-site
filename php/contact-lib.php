<?php
/**
 * contact-lib.php — the contact form's mail handler machinery: Turnstile
 * verification, a per-IP rate limit, mail-header safety and sending.
 * send.php calls contact_init() with the settings the build wrote into
 * config.php, then contact_gate() and contact_send().
 *
 * Every function is prefixed contact_ so nothing here can collide with
 * anything shared hosting defines.
 */

// ── Defaults and config ─────────────────────────────────────────────────────

/**
 * Store (and read back) this request's settings. Called once per handler.
 * A static beats a global: nothing else can reach in and change it.
 */
function contact_init(array $cfg = []): array
{
    static $stored = null;

    if ($stored === null || $cfg !== []) {
        $stored = $cfg + [
            // Where mail goes, and who it comes from. mail_from should be on a
            // domain whose SPF record lists this server, or mail lands in spam.
            // It is also passed as the envelope sender (sendmail -f), which is
            // what SPF actually checks.
            'mail_to'     => '',
            'mail_from'   => '',
            'subject_tag' => 'Contact form',
            'return_page' => '/contact/',

            // Turnstile. No secret → verification is skipped, so the form keeps
            // working before the captcha is set up.
            'turnstile_secret' => '',
            'action'      => '',      // expected data-action, '' = don't check

            // Sliding-window rate limit, per IP, in the system temp directory.
            // The prefix keeps this site's files apart from anything else there.
            'rl_prefix'   => 'ctrl_',
            'rl_max'      => 5,
            'rl_window'   => 3600,

            // 0 disables the fill-time check (the no-JS form cannot report it).
            'min_fill_ms' => 0,

            'max_name'    => 120,
            'max_message' => 5000,
        ];
    }

    return $stored;
}

/** One setting, by key. */
function contact_opt(string $key)
{
    $cfg = contact_init();
    return $cfg[$key] ?? null;
}

// ── Header and text safety ──────────────────────────────────────────────────

/** Collapse anything that could break out of a mail header onto one line. */
function contact_header_safe(string $s): string
{
    return trim(str_replace(["\r", "\n", "\0"], ' ', $s));
}

/**
 * RFC 2047-encode a header value containing non-ASCII bytes. Without this a
 * name like "José" or an em dash lands in Subject: as raw UTF-8, which some
 * mail clients render as mojibake. mbstring is not guaranteed on shared
 * hosting, hence the hand-rolled fallback.
 */
function contact_mime_header(string $s): string
{
    if (preg_match('/[\x80-\xFF]/', $s) !== 1) {
        return $s;
    }
    if (function_exists('mb_encode_mimeheader')) {
        return mb_encode_mimeheader($s, 'UTF-8', 'B');
    }
    return '=?UTF-8?B?' . base64_encode($s) . '?=';
}

/** Trim to a character budget, with a byte-wise fallback without mbstring. */
function contact_cut(string $s, int $n): string
{
    return function_exists('mb_substr') ? mb_substr($s, 0, $n) : substr($s, 0, $n);
}

// ── Replying to the browser ─────────────────────────────────────────────────

/**
 * Answer the post and stop. JSON when the page asked for it (ajax=1), else a
 * redirect back to the form with a status flag the page's script reads.
 * $reason is a short machine-readable code so the no-JS page can say something
 * more useful than "something went wrong".
 */
function contact_respond(string $status, string $message = '', string $reason = ''): void
{
    if (($_POST['ajax'] ?? '') === '1') {
        header('Content-Type: application/json; charset=UTF-8');
        header('Cache-Control: no-store');
        echo json_encode(['status' => $status, 'message' => $message]);
    } else {
        $url = (string) contact_opt('return_page') . '?status=' . urlencode($status);
        if ($reason !== '') {
            $url .= '&reason=' . urlencode($reason);
        }
        header('Location: ' . $url);
    }
    exit;
}

// ── Rate limiting ───────────────────────────────────────────────────────────

/**
 * REMOTE_ADDR only. X-Forwarded-For is client-supplied and would let a bot mint
 * a fresh identity per request, defeating the limit entirely.
 */
function contact_client_ip(): string
{
    return (string) ($_SERVER['REMOTE_ADDR'] ?? '0.0.0.0');
}

function contact_rl_path(): string
{
    return sys_get_temp_dir() . '/'
         . (string) contact_opt('rl_prefix')
         . sha1(contact_client_ip());
}

/** Timestamps of this IP's recent sends through this form, oldest first. */
function contact_rl_stamps(): array
{
    $path = contact_rl_path();
    if (!is_readable($path)) {
        return [];
    }
    $now    = time();
    $window = (int) contact_opt('rl_window');
    $stamps = [];
    foreach (explode(',', (string) @file_get_contents($path)) as $part) {
        $t = (int) $part;
        if ($t > 0 && ($now - $t) < $window) {
            $stamps[] = $t;
        }
    }
    return $stamps;
}

/**
 * Checking and recording are deliberately separate: only a message we actually
 * try to send counts against the limit, so someone who mistypes their address
 * three times does not lock themselves out. Posts that fail validation send no
 * mail and so cost nothing worth rationing.
 *
 * Keyed on the IP rather than a PHP session: a session limit only binds
 * clients that keep cookies, which bots do not.
 */
function contact_rate_limited(): bool
{
    return count(contact_rl_stamps()) >= (int) contact_opt('rl_max');
}

function contact_rate_record(): void
{
    $stamps   = contact_rl_stamps();
    $stamps[] = time();
    @file_put_contents(contact_rl_path(), implode(',', $stamps), LOCK_EX);
}

// ── HTTP ────────────────────────────────────────────────────────────────────

/**
 * POST a form to a URL; the response body, or false. curl first: shared hosts
 * often turn off allow_url_fopen (TCH does on PHP 8.4), which the stream
 * fallback needs.
 */
function contact_post(string $url, array $fields)
{
    $body = http_build_query($fields);
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_POST           => true,
            CURLOPT_POSTFIELDS     => $body,
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT        => 8,
            CURLOPT_CONNECTTIMEOUT => 5,
            CURLOPT_HTTPHEADER     => ['Content-Type: application/x-www-form-urlencoded'],
        ]);
        $raw = curl_exec($ch);
        if (PHP_VERSION_ID < 80000) {
            curl_close($ch);          // a no-op since PHP 8, deprecated in 8.5
        }
        return is_string($raw) ? $raw : false;
    }
    if (!ini_get('allow_url_fopen')) {
        return false;
    }
    $ctx = stream_context_create(['http' => [
        'method'        => 'POST',
        'header'        => "Content-Type: application/x-www-form-urlencoded\r\n",
        'content'       => $body,
        'timeout'       => 8,
        'ignore_errors' => true,
    ]]);
    return @file_get_contents($url, false, $ctx);
}

// ── Turnstile ───────────────────────────────────────────────────────────────

/**
 * True when Turnstile passes, or when no secret is configured.
 *
 * $detail comes back as a short human-readable note for the email body — the
 * hostname Cloudflare says the widget ran on, and the action it carried. That
 * is the only way to see which hostname actually needs registering when the
 * widget is inside a cross-site iframe.
 */
function contact_turnstile_ok(?string &$detail = null): bool
{
    $detail = 'not configured';

    $secret = trim((string) contact_opt('turnstile_secret'));
    if ($secret === '') {
        return true;  // captcha not set up yet
    }

    $token = (string) ($_POST['cf-turnstile-response'] ?? '');
    if ($token === '') {
        // The page sends no token when its site key is blank. Deploying the
        // secret before the HTML therefore rejects everyone — see the README.
        $detail = 'no token sent';
        return false;
    }

    $raw = contact_post(
        'https://challenges.cloudflare.com/turnstile/v0/siteverify',
        [
            'secret'   => $secret,
            'response' => $token,
            'remoteip' => contact_client_ip(),
        ]
    );
    if ($raw === false) {
        $detail = 'siteverify unreachable';
        return false;
    }

    $parsed = json_decode($raw, true);
    if (!is_array($parsed) || empty($parsed['success'])) {
        $codes = '';
        if (is_array($parsed) && !empty($parsed['error-codes'])) {
            $codes = ' (' . contact_header_safe(
                implode(', ', array_map('strval', (array) $parsed['error-codes']))
            ) . ')';
        }
        $detail = 'failed' . $codes;
        return false;
    }

    $hostname = contact_header_safe((string) ($parsed['hostname'] ?? ''));
    $action   = contact_header_safe((string) ($parsed['action'] ?? ''));
    $expected = (string) contact_opt('action');

    // Checked leniently on purpose. A token with no action is accepted, so a
    // page deployed before its data-action was added keeps working; a token
    // carrying the OTHER form's action is refused.
    if ($expected !== '' && $action !== '' && $action !== $expected) {
        $detail = 'wrong form (' . $action . ')';
        return false;
    }

    $detail = 'passed'
            . ($hostname !== '' ? ' on ' . $hostname : '')
            . ($action !== '' ? ' / ' . $action : '');
    return true;
}

// ── Sending ─────────────────────────────────────────────────────────────────

/**
 * Build and send the mail. $extra is printed in the body as label => value,
 * after Email and before the message — used for the Source and Captcha lines.
 * Returns mail()'s verdict. Records against the rate limit first, because by
 * this point we really are sending.
 */
function contact_send(string $name, string $email, string $message, array $extra = []): bool
{
    $name    = contact_cut($name, (int) contact_opt('max_name'));
    $message = contact_cut($message, (int) contact_opt('max_message'));

    // ASCII hyphen as the separator; contact_mime_header() covers the name.
    $subject = contact_mime_header(
        (string) contact_opt('subject_tag') . ': ' . $name
    );

    // Plain-text body, so no HTML escaping: htmlspecialchars() here would turn
    // apostrophes and ampersands into entities in the email you read.
    $body = "Name:    {$name}\n"
          . "Email:   {$email}\n";
    foreach ($extra as $label => $value) {
        $body .= str_pad($label . ':', 9) . $value . "\n";
    }
    $body .= "\nMessage:\n{$message}\n";

    $headers = 'From: ' . (string) contact_opt('mail_from') . "\r\n"
             . 'Reply-To: ' . $email . "\r\n"
             . "Content-Type: text/plain; charset=UTF-8\r\n"
             . 'X-Mailer: PHP/' . PHP_VERSION;

    contact_rate_record();

    $from = (string) contact_opt('mail_from');
    $params = filter_var($from, FILTER_VALIDATE_EMAIL) ? '-f' . $from : '';

    return mail((string) contact_opt('mail_to'), $subject, $body, $headers, $params);
}

// ── The shared gate ─────────────────────────────────────────────────────────

/**
 * Everything both handlers do between "a post arrived" and "we have clean
 * values". Returns [name, email, message] or answers the browser and exits.
 */
function contact_gate(): array
{
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
        header('Location: ' . (string) contact_opt('return_page'));
        exit;
    }

    // Honeypot. Report success so the bot does not retry with it cleared.
    if (trim((string) ($_POST['website'] ?? '')) !== '') {
        contact_respond('success');
    }

    // Submitted faster than a human can type. Client-reported, so a bot posting
    // straight here can forge it — this stops naive form-fillers only.
    $min = (int) contact_opt('min_fill_ms');
    if ($min > 0) {
        $elapsed = (int) ($_POST['elapsed'] ?? 0);
        if ($elapsed > 0 && $elapsed < $min) {
            contact_respond('success');
        }
    }

    if (contact_rate_limited()) {
        contact_respond(
            'error',
            'Too many messages from this connection. Please try again later.',
            'ratelimit'
        );
    }

    $detail = '';
    if (!contact_turnstile_ok($detail)) {
        contact_respond(
            'error',
            'The verification check did not pass. Please try again.',
            'captcha'
        );
    }

    $name    = contact_header_safe((string) ($_POST['name'] ?? ''));
    $message = trim((string) ($_POST['message'] ?? ''));
    $email   = filter_var(
        trim((string) ($_POST['email'] ?? '')),
        FILTER_VALIDATE_EMAIL
    );

    if ($name === '' || $message === '' || $email === false) {
        contact_respond(
            'error',
            'Please fill in your name, a valid email address, and a message.',
            'invalid'
        );
    }

    // $email is header-safe by construction: FILTER_VALIDATE_EMAIL rejects CR/LF.
    return [$name, $email, $message, $detail];
}
