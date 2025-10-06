<?php
// The target URL you want to embed.
$url = 'https://www.tamildhool.tech/vijay-tv/vijay-tv-show/bigg-boss-tamil-s9/bigg-boss-tamil-s9-live-stream-24x7-vijay-tv-show/';

// Initialize a cURL session. cURL is a library for transferring data with URLs.
$ch = curl_init();

// Set cURL options.
// CURLOPT_URL: The URL to fetch.
// CURLOPT_RETURNTRANSFER: Return the transfer as a string instead of outputting it directly.
// CURLOPT_FOLLOWLOCATION: Follow any "Location: " headers that the server sends (for redirects).
// CURLOPT_USERAGENT: Set a user agent string to mimic a real browser, as some sites block requests without one.
curl_setopt($ch, CURLOPT_URL, $url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
curl_setopt($ch, CURLOPT_USERAGENT, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36');

// Execute the cURL session and get the content.
$html = curl_exec($ch);

// Check for errors.
if (curl_errno($ch)) {
    echo 'cURL error: ' . curl_error($ch);
    exit;
}

// Close the cURL session.
curl_close($ch);

// IMPORTANT: To make sure relative links for CSS, JavaScript, and images work correctly,
// we inject a <base> tag into the <head> of the fetched HTML. This tells the browser
// to load all relative resources from the original website's domain.
$baseUrl = 'https://www.tamildhool.tech/';
$html = str_ireplace('<head>', '<head><base href="' . $baseUrl . '">', $html);

// Output the final HTML.
echo $html;
?>
