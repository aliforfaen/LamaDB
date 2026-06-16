-- Migration 029: Seed initial RSS feeds for agent-driven content
-- Seeds four default feeds (Lamalab, Media, Life, Briefing) that agents can
-- publish agent_feed documents into. ON CONFLICT keeps this idempotent so
-- re-runs after the seed are safe.

INSERT INTO feeds (name, slug, description, filter_tags, filter_source_types, max_items)
VALUES
  ('LamaLab', 'lamalab', 'Homelab updates: service status, agent activity, deployments, infra alerts',
   ARRAY['homelab', 'service', 'agent', 'infra'], ARRAY['agent_feed'], 50),
  ('Media', 'media', 'Media stack: new Plex content, watch history, download updates',
   ARRAY['media', 'notflix', 'plex'], ARRAY['agent_feed'], 30),
  ('Life', 'life', 'Life management: reminders, task completions, health nudges, appointments',
   ARRAY['reminder', 'todo', 'health', 'life'], ARRAY['agent_feed'], 30),
  ('Briefing', 'briefing', 'Agent briefings: morning brief, evening wind-down, weekly review',
   ARRAY['briefing', 'digest'], ARRAY['agent_feed'], 20)
ON CONFLICT (slug) DO NOTHING;
