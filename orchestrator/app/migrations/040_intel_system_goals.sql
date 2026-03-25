-- Migration 040: Seed system intelligence goals and default feeds

-- Add unique constraint on feed URL for idempotent seeding
CREATE UNIQUE INDEX IF NOT EXISTS idx_intel_feeds_url ON intel_feeds(url);

-- System goals (idempotent: ON CONFLICT DO NOTHING)
INSERT INTO goals (id, title, description, status, priority, schedule_cron, max_completions,
                   max_cost_usd, check_interval_seconds, created_via, created_by)
VALUES
    ('d0000000-0000-0000-0000-000000000001',
     'Daily Intelligence Sweep',
     'Read all new intel content, cross-reference with engram memory, classify and build knowledge network.',
     'active', 5, '0 6 * * *', NULL, 0.50, 86400, 'system', 'system'),
    ('d0000000-0000-0000-0000-000000000002',
     'Weekly Intelligence Synthesis',
     'Find knowledge clusters, generate graded recommendations, re-evaluate deferred recommendations.',
     'active', 5, '0 8 * * 1', NULL, 2.00, 604800, 'system', 'system'),
    ('d0000000-0000-0000-0000-000000000003',
     'Self-Improvement Check',
     'Compare Nova capabilities against accumulated intelligence. Identify gaps, suggest improvements.',
     'active', 4, '0 10 * * 3,6', NULL, 1.50, 345600, 'system', 'system')
ON CONFLICT (id) DO NOTHING;

-- Default feeds (idempotent via unique URL constraint)
INSERT INTO intel_feeds (name, url, feed_type, category, check_interval_seconds) VALUES
    ('r/artificial', 'https://old.reddit.com/r/artificial/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/artificialintelligence', 'https://old.reddit.com/r/artificialintelligence/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/openai', 'https://old.reddit.com/r/openai/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/ClaudeAI', 'https://old.reddit.com/r/ClaudeAI/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/LocalLLaMA', 'https://old.reddit.com/r/LocalLLaMA/new/.json', 'reddit_json', 'reddit', 43200),
    ('r/MachineLearning', 'https://old.reddit.com/r/MachineLearning/new/.json', 'reddit_json', 'reddit', 86400),
    ('r/aitoolsupdate', 'https://old.reddit.com/r/aitoolsupdate/new/.json', 'reddit_json', 'reddit', 43200),
    ('Anthropic Blog', 'https://www.anthropic.com/feed.xml', 'rss', 'blog', 21600),
    ('OpenAI Blog', 'https://openai.com/news/rss.xml', 'rss', 'blog', 21600),
    ('Google AI Blog', 'https://blog.google/innovation-and-ai/technology/ai/rss/', 'rss', 'blog', 43200),
    ('Ollama Releases', 'https://github.com/ollama/ollama/releases.atom', 'github_releases', 'tooling', 86400),
    ('vLLM Releases', 'https://github.com/vllm-project/vllm/releases.atom', 'github_releases', 'tooling', 86400),
    ('LiteLLM Releases', 'https://github.com/BerriAI/litellm/releases.atom', 'github_releases', 'tooling', 86400),
    ('GitHub Trending AI/ML', 'https://github.com/trending?since=daily', 'github_trending', 'github', 86400)
ON CONFLICT (url) DO NOTHING;
