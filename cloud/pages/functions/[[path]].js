// Everything at this address is the Stage Cloud Worker's: pass the request on, untouched
// (its URL keeps this address, so the Worker's same-origin checks and cookies fit it).
export const onRequest = ({ request, env }) => env.CLOUD.fetch(request);