/**
 * Design Review Agent using Playwright
 *
 * This script navigates through the UI, takes screenshots, and provides
 * constructive feedback on the design and UX.
 *
 * Usage:
 *   npx tsx scripts/design-review.ts
 *
 * Prerequisites:
 *   - npm install -D playwright @playwright/test tsx
 *   - npx playwright install chromium
 *   - Dev server running on localhost:3000
 */

import { chromium, Browser, Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';

interface PageReview {
  page: string;
  url: string;
  screenshot: string;
  issues: DesignIssue[];
  suggestions: string[];
  score: number;
}

interface DesignIssue {
  severity: 'critical' | 'warning' | 'info';
  category: 'accessibility' | 'spacing' | 'typography' | 'color' | 'layout' | 'interaction' | 'consistency';
  element?: string;
  description: string;
  recommendation: string;
}

interface DesignReviewReport {
  timestamp: string;
  overallScore: number;
  pages: PageReview[];
  summary: {
    totalIssues: number;
    critical: number;
    warnings: number;
    info: number;
  };
  recommendations: string[];
}

const PAGES_TO_REVIEW = [
  { name: 'Home / Extract', path: '/' },
  { name: 'Jobs', path: '/jobs' },
  { name: 'Schemas', path: '/schemas' },
  { name: 'Providers', path: '/providers' },
  { name: 'Settings', path: '/settings' },
];

const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';
const OUTPUT_DIR = 'design-review-output';

async function analyzePageDesign(page: Page, pageName: string): Promise<DesignIssue[]> {
  const issues: DesignIssue[] = [];

  // Check for accessibility issues
  const accessibilityChecks = await page.evaluate(() => {
    const issues: { element: string; description: string }[] = [];

    // Check images without alt text
    document.querySelectorAll('img:not([alt])').forEach((img, i) => {
      issues.push({
        element: `img[${i}]`,
        description: 'Image missing alt text',
      });
    });

    // Check buttons without accessible names
    document.querySelectorAll('button').forEach((btn, i) => {
      const text = btn.textContent?.trim();
      const ariaLabel = btn.getAttribute('aria-label');
      if (!text && !ariaLabel) {
        issues.push({
          element: `button[${i}]`,
          description: 'Button without accessible text',
        });
      }
    });

    // Check for low contrast text (basic check)
    document.querySelectorAll('*').forEach((el) => {
      const style = getComputedStyle(el);
      const color = style.color;
      const bgColor = style.backgroundColor;
      // This is a simplified check - real contrast checking is more complex
      if (color === bgColor && color !== 'rgba(0, 0, 0, 0)') {
        issues.push({
          element: el.tagName.toLowerCase(),
          description: 'Potential low contrast text',
        });
      }
    });

    // Check for missing form labels
    document.querySelectorAll('input, select, textarea').forEach((input, i) => {
      const id = input.getAttribute('id');
      const ariaLabel = input.getAttribute('aria-label');
      const hasLabel = id ? document.querySelector(`label[for="${id}"]`) : null;
      if (!hasLabel && !ariaLabel) {
        issues.push({
          element: `input[${i}]`,
          description: 'Form input without associated label',
        });
      }
    });

    return issues;
  });

  accessibilityChecks.forEach((check) => {
    issues.push({
      severity: 'warning',
      category: 'accessibility',
      element: check.element,
      description: check.description,
      recommendation: 'Add proper accessibility attributes',
    });
  });

  // Check for consistent spacing
  const spacingIssues = await page.evaluate(() => {
    const issues: string[] = [];
    const cards = document.querySelectorAll('[class*="card"], [class*="Card"]');
    const margins = new Set<string>();

    cards.forEach((card) => {
      const style = getComputedStyle(card);
      margins.add(`${style.marginTop}-${style.marginBottom}`);
    });

    if (margins.size > 2) {
      issues.push('Inconsistent card spacing detected');
    }

    return issues;
  });

  spacingIssues.forEach((issue) => {
    issues.push({
      severity: 'info',
      category: 'spacing',
      description: issue,
      recommendation: 'Use consistent spacing tokens throughout the design',
    });
  });

  // Check for typography consistency
  const typographyIssues = await page.evaluate(() => {
    const issues: string[] = [];
    const headings = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
    const fontSizes = new Map<string, number>();

    headings.forEach((h) => {
      const tag = h.tagName.toLowerCase();
      const size = getComputedStyle(h).fontSize;
      if (!fontSizes.has(tag)) {
        fontSizes.set(tag, 0);
      }
      fontSizes.set(tag, (fontSizes.get(tag) || 0) + 1);
    });

    // Check heading hierarchy
    const h1Count = document.querySelectorAll('h1').length;
    if (h1Count > 1) {
      issues.push(`Multiple h1 elements found (${h1Count}). Consider using only one h1 per page.`);
    }

    return issues;
  });

  typographyIssues.forEach((issue) => {
    issues.push({
      severity: 'info',
      category: 'typography',
      description: issue,
      recommendation: 'Maintain proper heading hierarchy and consistency',
    });
  });

  // Check for interactive element sizing (touch targets)
  const touchTargetIssues = await page.evaluate(() => {
    const issues: { element: string; size: string }[] = [];
    const interactiveElements = document.querySelectorAll('button, a, input, select');

    interactiveElements.forEach((el, i) => {
      const rect = el.getBoundingClientRect();
      // Minimum touch target size is 44x44px (Apple HIG) or 48x48dp (Material)
      if (rect.width < 32 || rect.height < 32) {
        issues.push({
          element: `${el.tagName.toLowerCase()}[${i}]`,
          size: `${Math.round(rect.width)}x${Math.round(rect.height)}px`,
        });
      }
    });

    return issues;
  });

  if (touchTargetIssues.length > 0) {
    issues.push({
      severity: 'warning',
      category: 'interaction',
      description: `${touchTargetIssues.length} interactive elements may be too small for easy touch/click`,
      recommendation: 'Ensure all interactive elements are at least 44x44px for accessibility',
    });
  }

  // Check for visual hierarchy
  const layoutIssues = await page.evaluate(() => {
    const issues: string[] = [];

    // Check for centered content
    const mainContent = document.querySelector('main') || document.querySelector('[role="main"]');
    if (!mainContent) {
      issues.push('No semantic <main> element or role="main" found');
    }

    // Check for proper navigation structure
    const nav = document.querySelector('nav') || document.querySelector('[role="navigation"]');
    if (!nav) {
      issues.push('No semantic <nav> element or role="navigation" found');
    }

    // Check empty states
    const emptyContainers = document.querySelectorAll('[class*="empty"], [class*="Empty"]');
    if (emptyContainers.length === 0) {
      // Check if there are containers that might need empty states
      const lists = document.querySelectorAll('[class*="list"], [class*="grid"]');
      lists.forEach((list) => {
        if (list.children.length === 0) {
          issues.push('Empty container without empty state messaging');
        }
      });
    }

    return issues;
  });

  layoutIssues.forEach((issue) => {
    issues.push({
      severity: 'info',
      category: 'layout',
      description: issue,
      recommendation: 'Follow semantic HTML best practices for better accessibility and SEO',
    });
  });

  return issues;
}

function generateSuggestions(issues: DesignIssue[], pageName: string): string[] {
  const suggestions: string[] = [];

  // Group issues by category
  const byCategory = issues.reduce((acc, issue) => {
    if (!acc[issue.category]) {
      acc[issue.category] = [];
    }
    acc[issue.category].push(issue);
    return acc;
  }, {} as Record<string, DesignIssue[]>);

  // Generate suggestions based on patterns
  if (byCategory.accessibility && byCategory.accessibility.length > 3) {
    suggestions.push(
      `Consider an accessibility audit for ${pageName}. Multiple a11y issues detected.`
    );
  }

  if (byCategory.spacing && byCategory.spacing.length > 0) {
    suggestions.push(
      'Standardize spacing using a consistent design system (e.g., 4px, 8px, 16px, 24px, 32px grid)'
    );
  }

  if (byCategory.typography && byCategory.typography.length > 0) {
    suggestions.push(
      'Review typography hierarchy to ensure clear visual importance structure'
    );
  }

  // Page-specific suggestions
  if (pageName.toLowerCase().includes('home') || pageName.toLowerCase().includes('extract')) {
    suggestions.push(
      'Home page should have a clear call-to-action and value proposition'
    );
  }

  if (pageName.toLowerCase().includes('settings')) {
    suggestions.push(
      'Settings pages should group related options and provide clear labels'
    );
  }

  return suggestions;
}

function calculateScore(issues: DesignIssue[]): number {
  let score = 100;

  issues.forEach((issue) => {
    switch (issue.severity) {
      case 'critical':
        score -= 15;
        break;
      case 'warning':
        score -= 5;
        break;
      case 'info':
        score -= 1;
        break;
    }
  });

  return Math.max(0, Math.min(100, score));
}

async function reviewPage(
  browser: Browser,
  pageConfig: { name: string; path: string },
  outputDir: string
): Promise<PageReview> {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    colorScheme: 'dark',
  });

  const page = await context.newPage();
  const url = `${BASE_URL}${pageConfig.path}`;

  console.log(`  Reviewing: ${pageConfig.name} (${url})`);

  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1000); // Wait for animations

    // Take screenshot
    const screenshotPath = path.join(outputDir, `${pageConfig.name.toLowerCase().replace(/[^a-z0-9]/g, '-')}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: true });

    // Analyze design
    const issues = await analyzePageDesign(page, pageConfig.name);
    const suggestions = generateSuggestions(issues, pageConfig.name);
    const score = calculateScore(issues);

    console.log(`    Score: ${score}/100 | Issues: ${issues.length}`);

    return {
      page: pageConfig.name,
      url,
      screenshot: screenshotPath,
      issues,
      suggestions,
      score,
    };
  } catch (error) {
    console.error(`    Error reviewing ${pageConfig.name}:`, error);
    return {
      page: pageConfig.name,
      url,
      screenshot: '',
      issues: [
        {
          severity: 'critical',
          category: 'layout',
          description: `Failed to load page: ${error}`,
          recommendation: 'Ensure the page loads correctly without errors',
        },
      ],
      suggestions: ['Fix page loading errors before design review'],
      score: 0,
    };
  } finally {
    await context.close();
  }
}

async function runDesignReview(): Promise<void> {
  console.log('\n============================================');
  console.log('  DESIGN REVIEW AGENT');
  console.log('  Powered by Playwright');
  console.log('============================================\n');

  // Create output directory
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const outputDir = path.join(OUTPUT_DIR, timestamp);
  fs.mkdirSync(outputDir, { recursive: true });

  console.log(`Output directory: ${outputDir}\n`);

  // Launch browser
  const browser = await chromium.launch({ headless: true });

  try {
    const pageReviews: PageReview[] = [];

    console.log('Reviewing pages...\n');

    for (const pageConfig of PAGES_TO_REVIEW) {
      const review = await reviewPage(browser, pageConfig, outputDir);
      pageReviews.push(review);
    }

    // Calculate summary
    const allIssues = pageReviews.flatMap((r) => r.issues);
    const summary = {
      totalIssues: allIssues.length,
      critical: allIssues.filter((i) => i.severity === 'critical').length,
      warnings: allIssues.filter((i) => i.severity === 'warning').length,
      info: allIssues.filter((i) => i.severity === 'info').length,
    };

    const overallScore = Math.round(
      pageReviews.reduce((sum, r) => sum + r.score, 0) / pageReviews.length
    );

    // Generate recommendations
    const recommendations: string[] = [];

    if (summary.critical > 0) {
      recommendations.push(
        `URGENT: Fix ${summary.critical} critical issues before deployment`
      );
    }

    if (summary.warnings > 5) {
      recommendations.push(
        'Consider a comprehensive accessibility review'
      );
    }

    // Category-specific recommendations
    const accessibilityIssues = allIssues.filter((i) => i.category === 'accessibility');
    if (accessibilityIssues.length > 0) {
      recommendations.push(
        `Accessibility: ${accessibilityIssues.length} issues found. Consider using aXe DevTools for detailed analysis.`
      );
    }

    const layoutIssues = allIssues.filter((i) => i.category === 'layout');
    if (layoutIssues.length > 0) {
      recommendations.push(
        'Layout: Ensure consistent use of semantic HTML elements'
      );
    }

    // Create report
    const report: DesignReviewReport = {
      timestamp: new Date().toISOString(),
      overallScore,
      pages: pageReviews,
      summary,
      recommendations,
    };

    // Save report
    const reportPath = path.join(outputDir, 'report.json');
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

    // Generate markdown report
    const markdownReport = generateMarkdownReport(report);
    const mdReportPath = path.join(outputDir, 'report.md');
    fs.writeFileSync(mdReportPath, markdownReport);

    // Print summary
    console.log('\n============================================');
    console.log('  DESIGN REVIEW COMPLETE');
    console.log('============================================\n');
    console.log(`Overall Score: ${overallScore}/100`);
    console.log(`\nIssues Found:`);
    console.log(`  Critical: ${summary.critical}`);
    console.log(`  Warnings: ${summary.warnings}`);
    console.log(`  Info: ${summary.info}`);
    console.log(`\nReports saved to: ${outputDir}`);
    console.log(`  - report.json (detailed)`);
    console.log(`  - report.md (readable)`);
    console.log(`  - Screenshots for each page\n`);

    if (recommendations.length > 0) {
      console.log('Top Recommendations:');
      recommendations.slice(0, 5).forEach((rec, i) => {
        console.log(`  ${i + 1}. ${rec}`);
      });
    }

    console.log('\n');
  } finally {
    await browser.close();
  }
}

function generateMarkdownReport(report: DesignReviewReport): string {
  let md = `# Design Review Report

**Generated:** ${new Date(report.timestamp).toLocaleString()}
**Overall Score:** ${report.overallScore}/100

## Summary

| Metric | Count |
|--------|-------|
| Total Issues | ${report.summary.totalIssues} |
| Critical | ${report.summary.critical} |
| Warnings | ${report.summary.warnings} |
| Info | ${report.summary.info} |

## Page Reviews

`;

  report.pages.forEach((page) => {
    md += `### ${page.page}

**URL:** ${page.url}
**Score:** ${page.score}/100
**Screenshot:** [View](${path.basename(page.screenshot)})

`;

    if (page.issues.length > 0) {
      md += `#### Issues\n\n`;
      page.issues.forEach((issue) => {
        const icon = issue.severity === 'critical' ? '🔴' : issue.severity === 'warning' ? '🟡' : '🔵';
        md += `- ${icon} **[${issue.category}]** ${issue.description}\n`;
        md += `  - *Recommendation:* ${issue.recommendation}\n`;
      });
      md += '\n';
    } else {
      md += `*No issues found*\n\n`;
    }

    if (page.suggestions.length > 0) {
      md += `#### Suggestions\n\n`;
      page.suggestions.forEach((suggestion) => {
        md += `- ${suggestion}\n`;
      });
      md += '\n';
    }
  });

  if (report.recommendations.length > 0) {
    md += `## Top Recommendations\n\n`;
    report.recommendations.forEach((rec, i) => {
      md += `${i + 1}. ${rec}\n`;
    });
  }

  return md;
}

// Run the review
runDesignReview().catch(console.error);
