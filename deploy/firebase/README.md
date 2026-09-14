# Firebase Hosting front door

`https://url-crawler.web.app` forwards every request to the Cloud Run service
`crawler` (us-central1). Hosting stores nothing; the rewrite is the whole site.

Deploy after `firebase login`:

    cd deploy/firebase && firebase deploy --only hosting
