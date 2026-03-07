-- Migration 013: Update default greeting to use {name} placeholder
-- Only updates rows that still have the original seed value.

UPDATE platform_config
SET value = '"Hello! I''m {name}. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?"'
WHERE key = 'nova.greeting'
  AND value = '"Hello! I''m Nova. I have access to your workspace, can run shell commands, read and write files, and remember our previous conversations. What would you like to work on?"';
