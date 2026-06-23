#!/usr/bin/env node

import { Command } from 'commander';
import Parser from 'rss-parser';
import chalk from 'chalk';
import open from 'open';
import readline from 'readline';

const parser = new Parser();
const program = new Command();

program
  .name('google-news')
  .description('A CLI tool to fetch the latest news from Google News and the Official Google Blog')
  .version('1.0.0')
  .option('-q, --query <string>', 'Search query on Google News')
  .option('-t, --topic <string>', 'Topic on Google News (e.g. TECHNOLOGY, BUSINESS, SCIENCE, WORLD, SPORTS, HEALTH)')
  .option('-b, --blog', 'Fetch news from the Official Google Blog (The Keyword)')
  .option('-l, --limit <number>', 'Number of news items to display', '10')
  .option('-n, --no-interactive', 'Disable interactive prompt to open articles');

program.parse(process.argv);
const options = program.opts();

async function main() {
  // Determine URL
  let url = 'https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en';
  let titleText = 'Top Headlines';

  if (options.blog) {
    url = 'https://blog.google/rss';
    titleText = 'Official Google Blog (The Keyword)';
  } else if (options.query) {
    url = `https://news.google.com/rss/search?q=${encodeURIComponent(options.query)}&hl=en-US&gl=US&ceid=US:en`;
    titleText = `Search Results for "${options.query}"`;
  } else if (options.topic) {
    const topicUpper = options.topic.toUpperCase();
    url = `https://news.google.com/rss/headlines/section/topic/${topicUpper}?hl=en-US&gl=US&ceid=US:en`;
    titleText = `Topic: ${topicUpper}`;
  }

  const limit = parseInt(options.limit, 10) || 10;

  console.log(chalk.bold.blue('\n=================================================='));
  console.log(chalk.bold.cyan(` Fetching news: ${titleText}`));
  console.log(chalk.bold.blue('==================================================\n'));

  try {
    const feed = await parser.parseURL(url);
    const items = feed.items.slice(0, limit);

    if (items.length === 0) {
      console.log(chalk.yellow('No news items found.'));
      return;
    }

    items.forEach((item, index) => {
      const number = index + 1;
      const title = item.title;
      // Extract source name (Google News titles usually end with " - Source Name")
      let cleanTitle = title;
      let source = '';
      if (!options.blog) {
        const lastDash = title.lastIndexOf(' - ');
        if (lastDash !== -1) {
          cleanTitle = title.substring(0, lastDash);
          source = title.substring(lastDash + 3);
        }
      } else {
        source = 'Google Keyword Blog';
      }

      const pubDate = item.pubDate ? new Date(item.pubDate).toLocaleString() : 'N/A';

      console.log(chalk.bold.green(`${number}. ${cleanTitle}`));
      if (source) {
        console.log(`   ${chalk.dim('Source:')} ${chalk.yellow(source)} | ${chalk.dim('Published:')} ${pubDate}`);
      } else {
        console.log(`   ${chalk.dim('Published:')} ${pubDate}`);
      }
      console.log(`   ${chalk.blue.underline(item.link)}\n`);
    });

    // Interactive prompt
    if (options.interactive && process.stdout.isTTY && process.stdin.isTTY) {
      const rl = readline.createInterface({
        input: process.stdin,
        output: process.stdout
      });

      const askQuestion = () => {
        rl.question(chalk.bold.cyan('Enter article number to open in browser (or q to quit): '), async (answer) => {
          if (answer.toLowerCase() === 'q' || answer.trim() === '') {
            rl.close();
            console.log(chalk.green('Goodbye!'));
            process.exit(0);
          }

          const index = parseInt(answer, 10) - 1;
          if (index >= 0 && index < items.length) {
            const article = items[index];
            console.log(chalk.green(`Opening: "${article.title}"...`));
            await open(article.link);
            askQuestion();
          } else {
            console.log(chalk.red('Invalid article number. Please try again.'));
            askQuestion();
          }
        });
      };

      askQuestion();
    }
  } catch (error) {
    console.error(chalk.red('\nError fetching or parsing the news feed:'));
    console.error(chalk.red(error.message));
    process.exit(1);
  }
}

main();
