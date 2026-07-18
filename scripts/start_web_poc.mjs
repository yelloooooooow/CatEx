import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(scriptDirectory, '..')
const webRoot = join(repositoryRoot, 'apps', 'web')
const python = join(repositoryRoot, '.venvs', 'catex-core-py312', 'Scripts', 'python.exe')
const viteScript = join(webRoot, 'node_modules', 'vite', 'bin', 'vite.js')

function option(name, fallback) {
  const prefix = `--${name}=`
  const value = process.argv.slice(2).find((argument) => argument.startsWith(prefix))
  return value ? value.slice(prefix.length) : fallback
}

const apiPort = Number(option('api-port', '8000'))
const webPort = Number(option('web-port', '5173'))
const keepAliveSeconds = Number(option('keep-alive-seconds', '0'))
const openBrowser = !process.argv.includes('--no-browser')
const apiUrl = `http://127.0.0.1:${apiPort}`
const webUrl = `http://127.0.0.1:${webPort}`
const children = []
let stopping = false

for (const [label, value] of [
  ['API port', apiPort],
  ['Web port', webPort],
]) {
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${label} must be an integer from 1 to 65535.`)
  }
}

if (!existsSync(python)) {
  throw new Error(`CatEx Python environment not found: ${python}`)
}
if (!existsSync(viteScript)) {
  throw new Error("Frontend dependencies are missing. Run 'pnpm install --frozen-lockfile' first.")
}

function start(command, args, cwd, environment = process.env) {
  const child = spawn(command, args, {
    cwd,
    env: environment,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.output = ''
  const remember = (chunk) => {
    child.output = `${child.output}${chunk}`.slice(-8000)
  }
  child.stdout.on('data', remember)
  child.stderr.on('data', remember)
  children.push(child)
  return child
}

function portIsAvailable(port) {
  return new Promise((resolveAvailability) => {
    const server = createServer()
    server.unref()
    server.once('error', () => resolveAvailability(false))
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      server.close(() => resolveAvailability(true))
    })
  })
}

async function waitFor(url, accept, child, attempts) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(1000) })
      if (response.ok && (await accept(response))) return true
    } catch {
      // The service is still starting; the bounded loop reports a final error.
    }
    if (child.exitCode !== null) break
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200))
  }
  return false
}

async function stop(exitCode = 0) {
  if (stopping) return
  stopping = true
  process.stdout.write('\nStopping local CatEx services...\n')
  for (const child of children.reverse()) {
    if (child.exitCode === null) child.kill()
  }
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 250))
  process.exit(exitCode)
}

process.on('SIGINT', () => void stop(0))
process.on('SIGTERM', () => void stop(0))

try {
  if (apiPort === webPort) {
    throw new Error('API and Web ports must be different.')
  }
  if (!(await portIsAvailable(apiPort))) {
    throw new Error(
      `API port ${apiPort} is already in use. Stop the previous CatEx process or choose --api-port=<free-port>.`,
    )
  }
  if (!(await portIsAvailable(webPort))) {
    throw new Error(
      `Web port ${webPort} is already in use. Stop the previous CatEx process or choose --web-port=<free-port>.`,
    )
  }
  process.stdout.write('[1/3] Starting the local CatEx API...\n')
  const api = start(
    python,
    ['-m', 'uvicorn', 'catex_web.app:app', '--host', '127.0.0.1', '--port', String(apiPort)],
    repositoryRoot,
  )
  const apiReady = await waitFor(
    `${apiUrl}/api/v1/capabilities`,
    async (response) => Boolean((await response.json()).catex_version),
    api,
    75,
  )
  if (!apiReady) throw new Error(`CatEx API did not become ready on ${apiUrl}.\n${api.output}`)
  process.stdout.write('      API ready.\n')

  process.stdout.write('[2/3] Starting the local Web workbench...\n')
  const web = start(
    process.execPath,
    [viteScript, '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'],
    webRoot,
    { ...process.env, VITE_CATEX_API_URL: apiUrl },
  )
  const webReady = await waitFor(
    webUrl,
    async (response) => (await response.text()).includes('CatEx Workbench'),
    web,
    100,
  )
  if (!webReady) throw new Error(`CatEx Web workbench did not become ready on ${webUrl}.\n${web.output}`)
  process.stdout.write('      Web workbench ready.\n')

  process.stdout.write(`[3/3] CatEx is running at ${webUrl}\n`)
  if (openBrowser) {
    const browser = spawn('explorer.exe', [webUrl], { detached: true, stdio: 'ignore' })
    browser.unref()
  }

  process.stdout.write('\nKeep this window open while using CatEx.\n')
  if (keepAliveSeconds > 0) {
    setTimeout(() => void stop(0), keepAliveSeconds * 1000)
  } else {
    process.stdout.write('Press Enter here to stop CatEx.\n')
    process.stdin.resume()
    process.stdin.once('data', () => void stop(0))
  }
} catch (error) {
  process.stderr.write(`\nCatEx could not start: ${error.message}\n`)
  await stop(1)
}
