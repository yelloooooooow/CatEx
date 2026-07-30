import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import test from 'node:test'

import { compatibleWorkbenchIsRunning } from './local_workbench_probe.mjs'

function listen(server) {
  return new Promise((resolveListen, rejectListen) => {
    server.once('error', rejectListen)
    server.listen(0, '127.0.0.1', () => resolveListen(server.address().port))
  })
}

test('the readiness probe connects directly to localhost despite invalid proxy variables', async (t) => {
  process.env.HTTP_PROXY = 'http://127.0.0.1:9'
  process.env.HTTPS_PROXY = 'http://127.0.0.1:9'
  process.env.ALL_PROXY = 'http://127.0.0.1:9'
  process.env.NODE_USE_ENV_PROXY = '1'

  let requestCount = 0
  const server = createServer((request, response) => {
    requestCount += 1
    assert.equal(request.url, '/api/v1/capabilities')
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(
      JSON.stringify({
        schema_version: 'catex.web-capabilities.v1',
        catex_version: 'test',
      }),
    )
  })
  t.after(() => server.close())
  const port = await listen(server)

  assert.equal(await compatibleWorkbenchIsRunning(port), true)
  assert.equal(requestCount, 1)
})

test('the readiness probe rejects an unrelated local JSON service', async (t) => {
  const server = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ status: 'ok' }))
  })
  t.after(() => server.close())
  const port = await listen(server)

  assert.equal(await compatibleWorkbenchIsRunning(port), false)
})
