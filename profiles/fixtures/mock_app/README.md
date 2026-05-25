# OpsBoard Mock App

OpsBoard is a generic admin-style fixture used to exercise `site-agent` without target-specific core behavior.

Run it with Docker:

```bash
sudo docker build -t site-agent-opsboard profiles/fixtures/mock_app
sudo docker run --rm -p 8080:8080 site-agent-opsboard
```

Then crawl it with:

```bash
site-agent profile init --name opsboard --base-url http://127.0.0.1:8080
site-agent crawl run --profile opsboard
```

For dependency-free checks, crawl the static fixture directory:

```bash
site-agent crawl run --profile opsboard --fixture-site profiles/fixtures/mock_app/site
```
