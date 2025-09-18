import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  guideSidebar: [
    {
      type: 'category',
      label: 'Welcome',
      collapsed: false,
      items: ['intro'],
    },
    {
      type: 'category',
      label: 'Getting Started',
      items: [
        'getting-started/quickstart',
        'getting-started/configuration',
        'getting-started/docker-compose',
      ],
    },
    {
      type: 'category',
      label: 'User Guides',
      items: [
        'user-guides/admin-portal',
        'user-guides/api-reference',
        'user-guides/sync-operations',
      ],
    },
    {
      type: 'category',
      label: 'Data & Architecture',
      items: [
        'architecture/overview',
        'architecture/services',
        'data-catalog/data-model',
      ],
    },
    {
      type: 'category',
      label: 'Operations',
      items: [
        'operations/operations-overview',
        'operations/deployment',
        'operations/troubleshooting',
      ],
    },
    {
      type: 'category',
      label: 'Development',
      items: [
        'development/environment',
        'development/testing',
        'development/contributing',
      ],
    },
  ],
};

export default sidebars;
