import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { createServer } from 'node:net'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDirectory = dirname(fileURLToPath(import.meta.url))
const repositoryRoot = resolve(scriptDirectory, '..')
const webRoot = join(repositoryRoot, 'apps', 'web')
const webDist = join(webRoot, 'dist', 'index.html')
const portArgument = process.argv.find((argument) => argument.startsWith('--port='))
const port = Number(portArgument?.slice('--port='.length) ?? '8000')
const keepAliveArgument = process.argv.find((argument) =>
  argument.startsWith('--keep-alive-seconds='),
)
const keepAliveSeconds = Number(
  keepAliveArgument?.slice('--keep-alive-seconds='.length) ?? '0',
)
const openBrowser = !process.argv.includes('--no-browser')
const url = `http://127.0.0.1:${port}`

function findPython() {
  const configured = process.env.CATEX_PYTHON
  const candidates = [
    configured,
    join(repositoryRoot, '.venv', 'Scripts', 'python.exe'),
    join(repositoryRoot, '.venvs', 'catex-core-py312', 'Scripts', 'python.exe'),
  ].filter(Boolean)
  return candidates.find((candidate) => existsSync(candidate))
}

function portIsAvailable() {
  return new Promise((resolveAvailability) => {
    const server = createServer()
    server.unref()
    server.once('error', () => resolveAvailability(false))
    server.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      server.close(() => resolveAvailability(true))
    })
  })
}

async function compatibleWorkbenchIsRunning() {
  try {
    const response = await fetch(`${url}/api/v1/capabilities`, {
      signal: AbortSignal.timeout(1500),
    })
    return response.ok && Boolean((await response.json()).catex_version)
  } catch {
    return false
  }
}

function openWorkbench() {
  const browser = spawn('explorer.exe', [url], {
    detached: true,
    stdio: 'ignore',
    windowsHide: true,
  })
  browser.unref()
}

async function waitForWorkbench(child) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) return false
    if (await compatibleWorkbenchIsRunning()) return true
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 200))
  }
  return false
}

if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('Port must be an integer from 1 to 65535.')
}
const python = findPython()
if (!python) {
  throw new Error(
    'CatEx Python environment was not found. Create .venv or set CATEX_PYTHON.',
  )
}

if (!existsSync(webDist)) {
  process.stdout.write('[1/3] Building the CatEx Web interface...\n')
  const build = spawnSync(
    process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm',
    ['--dir', webRoot, 'build'],
    { cwd: repositoryRoot, stdio: 'inherit', windowsHide: true },
  )
  if (build.status !== 0 || !existsSync(webDist)) {
    throw new Error(
      "The Web build failed. Run 'pnpm install --frozen-lockfile' and try again.",
    )
  }
} else {
  process.stdout.write('[1/3] Reusing the built CatEx Web interface.\n')
}

if (!(await portIsAvailable())) {
  if (await compatibleWorkbenchIsRunning()) {
    process.stdout.write(`[2/3] CatEx is already running at ${url}.\n`)
    if (openBrowser) openWorkbench()
    process.exit(0)
  }
  throw new Error(`Port ${port} is already in use by another application.`)
}

process.stdout.write('[2/3] Starting the local CatEx application...\n')
const child = spawn(
  python,
  ['-m', 'uvicorn', 'catex_web.app:app', '--host', '127.0.0.1', '--port', String(port)],
  {
    cwd: repositoryRoot,
    env: { ...process.env, CATEX_SERVE_WEB: '1' },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  },
)
child.stdout.pipe(process.stdout)
child.stderr.pipe(process.stderr)

if (!(await waitForWorkbench(child))) {
  child.kill()
  throw new Error(`CatEx did not become ready at ${url}.`)
}
process.stdout.write(`[3/3] CatEx is ready at ${url}\n`)
if (openBrowser) openWorkbench()

let stopping = false
function stop() {
  if (stopping) return
  stopping = true
  if (child.exitCode === null) child.kill()
}
process.on('SIGINT', stop)
process.on('SIGTERM', stop)
child.once('exit', (code) => process.exit(code ?? 0))

if (keepAliveSeconds > 0) {
  setTimeout(stop, keepAliveSeconds * 1000)
} else {
  process.stdout.write('Keep this window open while using CatEx; press Enter to stop.\n')
  process.stdin.resume()
  process.stdin.once('data', stop)
}
