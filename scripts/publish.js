#!/usr/bin/env node
'use strict';

// Publish this package to npm.
//
//   npm run publish              public, under the scope in package.json
//   npm run publish:private      restricted (needs a paid npm plan)
//   NPM_SCOPE=enzorenz npm run publish   publish under another scope
//
// The scope has to belong to the account you are logged in as, or to an
// organisation you belong to. npm refuses to create a brand new package name
// in a scope your account does not own, so switch accounts with
// "npm login --scope=@yourname" before publishing under a different scope.
//
// Your npm account has 2FA switched on, so npm wants proof that you are you.
// Either use a token that bypasses 2FA:
//
//   NPM_TOKEN=npm_xxx npm run publish
//
// Create it at
// https://www.npmjs.com/settings/<your-username>/access-tokens
// Pick "Granular" -> "Read and write packages" -> tick "Bypass 2FA".
// That token publishes on its own, no one-time code needed.
//
// Or use the 6 digit code from an authenticator app:
//
//   NPM_OTP=123456 npm run publish

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const pkgPath = path.join(__dirname, '..', 'package.json');
const original = fs.readFileSync(pkgPath, 'utf8');
const pkg = JSON.parse(original);

const bare = pkg.name.replace(/^@[^/]+\//, '');
const currentScope = (pkg.name.match(/^@([^/]+)\//) || [])[1] || '';
const scope = (process.env.NPM_SCOPE || currentScope).trim().toLowerCase();

if (!scope) {
  console.error(
    'Set NPM_SCOPE to the npm account or organisation you own.\n' +
    '  NPM_SCOPE=yourname npm run publish'
  );
  process.exit(1);
}

if (!/^[a-z0-9][a-z0-9._-]*$/.test(scope)) {
  console.error('"' + scope + '" is not a valid npm scope.');
  process.exit(1);
}

const access = process.env.NPM_ACCESS || (pkg.publishConfig && pkg.publishConfig.access) || 'public';
if (access !== 'public' && access !== 'restricted') {
  console.error('NPM_ACCESS must be "public" or "restricted".');
  process.exit(1);
}

pkg.name = '@' + scope + '/' + bare;
pkg.publishConfig = Object.assign({}, pkg.publishConfig, { access });

fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + '\n');
console.log('publishing ' + pkg.name + ' with ' + access + ' access');

const args = ['publish', '--access', access];
let tempRc = null;

if (process.env.NPM_TOKEN) {
  // A granular token with the "bypass 2FA" permission. Put it in a temp npmrc
  // so the secret never lands in the process arguments (visible via ps).
  const userRc = path.join(os.homedir(), '.npmrc');
  let base = '';
  try {
    base = fs.readFileSync(userRc, 'utf8');
  } catch (e) {
    base = '';
  }
  base = base.replace(/^\/\/registry\.npmjs\.org\/:_authToken=.*$/m, '');
  tempRc = path.join(os.tmpdir(), 'enzocli-npmrc-' + process.pid);
  fs.writeFileSync(
    tempRc,
    base.trimEnd() + '\n//registry.npmjs.org/:_authToken=' + process.env.NPM_TOKEN + '\n',
    { mode: 0o600 }
  );
  args.push('--userconfig=' + tempRc);
  console.log('using the token from NPM_TOKEN');
} else if (process.env.NPM_OTP) {
  // One-time code from the authenticator app.
  args.push('--otp=' + process.env.NPM_OTP);
  console.log('using the one-time code from NPM_OTP');
}

// Capture the output so we can explain the error instead of just showing it.
const result = spawnSync('npm', args, { encoding: 'utf8' });
if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);

if (tempRc) {
  try {
    fs.unlinkSync(tempRc);
  } catch (e) {
    /* nothing to do */
  }
}

if (result.status !== 0) {
  const out = (result.stdout || '') + (result.stderr || '');

  // npm stages a new version of an existing package and promotes it a little
  // later. Publishing the same version again then says it is already staged,
  // which means the publish did go through.
  const staged = out.match(/previously staged version "([^"]+)"/);
  if (staged) {
    fs.writeFileSync(pkgPath, original);
    console.log('');
    console.log('Version ' + staged[1] + ' is staged on npm and goes live shortly.');
    console.log('Check it with: npm view ' + pkg.name + ' versions');
    console.log('');
    console.log('Done. Install it with:');
    console.log('  npm install -g ' + pkg.name);
    process.exit(0);
  }

  fs.writeFileSync(pkgPath, original);

  console.error('');
  console.error('publish failed, package.json restored');

  if (out.includes('Payment Required') || out.includes('E402')) {
    console.error('');
    console.error('npm says you must sign up for private packages.');
    console.error('Private packages need a paid npm plan. Either upgrade, or');
    console.error('publish it publicly under a scope you own:');
    console.error('     npm run publish:public');
  } else if (out.includes('is not in this registry') || out.includes('E404')) {
    console.error('');
    console.error('npm will not create a new package name in the @' + scope + ' scope.');
    console.error('That scope belongs to a different npm account or organisation.');
    console.error('Log in as the account that owns it, then publish again:');
    console.error('     npm login --scope=@' + scope);
    console.error('     npm run publish');
    console.error('If you cannot log in as that account, publish under your own');
    console.error('scope instead:');
    console.error('     NPM_SCOPE=yourname npm run publish:public');
  } else if (out.includes('Two-factor authentication') || out.includes('E403')) {
    console.error('');
    console.error('Your npm account has 2FA switched on, so npm wants proof');
    console.error('you are you. Pick one of these:');
    console.error('');
    console.error('  1. A token that bypasses 2FA (no codes needed):');
    console.error('     https://www.npmjs.com/settings/fluctuateplus/access-tokens');
    console.error('     Generate New Token -> Granular -> "Read and write packages"');
    console.error('     -> tick "Bypass 2FA" -> copy the npm_... token');
    console.error('     then: NPM_TOKEN=npm_xxx npm run publish');
    console.error('');
    console.error('  2. A one-time code from an authenticator app:');
    console.error('     then: NPM_OTP=123456 npm run publish');
  }

  process.exit(result.status === null ? 1 : result.status);
}

console.log('');
console.log('Done. Install it with:');
console.log('  npm install -g ' + pkg.name);
if (access === 'restricted') {
  console.log('');
  console.log('Users need access granted from the npm package page,');
  console.log('or on a paid plan it stays private to your account.');
}
