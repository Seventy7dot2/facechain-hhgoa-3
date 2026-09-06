export function consumeEvents<T>(stream: ReadableStream<Uint8Array>, onEvent: (event: T) => void): Promise<void>;
