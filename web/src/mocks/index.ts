export async function setupMock() {
  if (import.meta.env.VITE_USE_MOCK === 'true') {
    const { worker } = await import('./browser')
    await worker.start({
      onUnhandledRequest: 'bypass',
      serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
    })
  }
}
