import { request } from 'node:http'

const MAX_RESPONSE_CHARACTERS = 64 * 1024

export function readLocalJson(port, pathname, timeoutMilliseconds = 1500) {
  return new Promise((resolvePayload) => {
    const localRequest = request(
      {
        agent: false,
        headers: { accept: 'application/json' },
        host: '127.0.0.1',
        method: 'GET',
        path: pathname,
        port,
      },
      (response) => {
        if (response.statusCode !== 200) {
          response.resume()
          resolvePayload(null)
          return
        }
        response.setEncoding('utf8')
        let body = ''
        response.on('data', (chunk) => {
          body += chunk
          if (body.length > MAX_RESPONSE_CHARACTERS) localRequest.destroy()
        })
        response.once('end', () => {
          try {
            resolvePayload(JSON.parse(body))
          } catch {
            resolvePayload(null)
          }
        })
      },
    )
    localRequest.setTimeout(timeoutMilliseconds, () => localRequest.destroy())
    localRequest.once('error', () => resolvePayload(null))
    localRequest.end()
  })
}

export async function compatibleWorkbenchIsRunning(port) {
  const capabilities = await readLocalJson(port, '/api/v1/capabilities')
  return Boolean(
    capabilities
      && capabilities.schema_version === 'catex.web-capabilities.v1'
      && typeof capabilities.catex_version === 'string'
      && capabilities.catex_version.length > 0,
  )
}
