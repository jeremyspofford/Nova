import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://nova.arialabs.ai',
  integrations: [
    starlight({
      title: 'Nova',
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/arialabs/nova' },
      ],
      customCss: ['./src/styles/global.css'],
      sidebar: [
        { label: 'Quick Start', slug: 'quickstart' },
        {
          label: 'Core Concepts',
          items: [
            { slug: 'architecture' },
            { slug: 'pipeline' },
            { slug: 'configuration' },
          ],
        },
        {
          label: 'Services',
          autogenerate: { directory: 'services' },
        },
        {
          label: 'Guides',
          items: [
            { slug: 'inference-backends' },
            { slug: 'deployment' },
            { slug: 'remote-access' },
            { slug: 'ide-integration' },
            { slug: 'mcp-tools' },
            { slug: 'skills-rules' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { slug: 'api-reference' },
            { slug: 'security' },
            { slug: 'roadmap' },
          ],
        },
      ],
    }),
  ],
  vite: { plugins: [tailwindcss()] },
});
