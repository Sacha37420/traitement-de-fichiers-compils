declare module 'imagetracerjs' {
  interface ImageTracerStatic {
    /** Trace une ImageData en SVG. `options` peut être un nom de preset ou un objet d'options. */
    imagedataToSVG(
      imgd: { width: number; height: number; data: Uint8ClampedArray },
      options?: string | Record<string, unknown>,
    ): string;
  }
  const ImageTracer: ImageTracerStatic;
  export default ImageTracer;
}
