import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Chicago Crash Data Pipeline',
  tagline: 'Comprehensive documentation for ingesting, managing, and exploring crash data',
  favicon: 'img/logo.svg',
  url: 'http://localhost:8000',
  baseUrl: '/documentation/',
  organizationName: 'MisterClean',
  projectName: 'chicago-crashes-pipeline',
  onBrokenLinks: 'warn', // Changed from 'throw' to allow external navigation links
  onBrokenMarkdownLinks: 'warn',
  staticDirectories: ['static'],
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      'classic',
      {
        docs: {
          path: 'docs',
          routeBasePath: '/',
          sidebarPath: './sidebars.ts',
          editUrl: 'https://github.com/MisterClean/chicago-crashes-pipeline/tree/main/',
          showLastUpdateTime: true,
          showLastUpdateAuthor: false,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
      navbar: {
      title: 'Crash Data Pipeline',
      items: [
        // Navigation links to other parts of the application (external to Docusaurus)
        // Using type: 'html' to prevent baseUrl prefixing
        {
          type: 'html',
          position: 'left',
          value: '<a href="/admin" class="navbar__item navbar__link">Admin Portal</a>',
        },
        {
          type: 'html',
          position: 'left',
          value: '<a href="/docs" class="navbar__item navbar__link">API Docs</a>',
        },
        {
          type: 'docSidebar',
          sidebarId: 'guideSidebar',
          position: 'left',
          label: 'Documentation',
        },
        {
          href: 'https://github.com/MisterClean/chicago-crashes-pipeline',
          label: 'GitHub',
          position: 'right',
        },
        {
          href: 'https://data.cityofchicago.org/',
          label: 'Chicago Data Portal',
          position: 'right',
        },
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Guides',
          items: [
            {label: 'Quick Start', to: '/getting-started/quickstart'},
            {label: 'Operations Handbook', to: '/operations/operations-overview'},
            {label: 'Admin Portal', to: '/user-guides/admin-portal'},
          ],
        },
        {
          title: 'Reference',
          items: [
            {label: 'API Reference', to: '/user-guides/api-reference'},
            {label: 'Data Catalog', to: '/data-catalog/data-model'},
            {label: 'Configuration', to: '/getting-started/configuration'},
          ],
        },
        {
          title: 'Community',
          items: [
            {label: 'GitHub Issues', href: 'https://github.com/MisterClean/chicago-crashes-pipeline/issues'},
            {label: 'Chicago Data Portal', href: 'https://data.cityofchicago.org/'},
          ],
        },
      ],
      copyright: `© ${new Date().getFullYear()} Chicago Crash Data Pipeline. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
      additionalLanguages: ['sql'],
    },
    colorMode: {
      defaultMode: 'light',
      respectPrefersColorScheme: true,
    },
    metadata: [
      {name: 'keywords', content: 'chicago crash data pipeline, etl, fastapi, postgis, docusaurus'},
      {name: 'description', content: 'End-user and operator documentation for the Chicago traffic crash data platform.'},
    ],
  },
};

export default config;
