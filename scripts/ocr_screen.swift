import Foundation
import Vision
import AppKit
let url=URL(fileURLWithPath:CommandLine.arguments[1])
let req=VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages=["zh-Hans","en-US"]
req.usesLanguageCorrection=false
try VNImageRequestHandler(url:url).perform([req])
let rows=(req.results ?? []).compactMap { r -> [String:Any]? in
 guard let t=r.topCandidates(1).first else{return nil}
 let b=r.boundingBox
 return ["text":t.string,"confidence":t.confidence,"x":b.minX,"y":1-b.maxY,"width":b.width,"height":b.height]
}
let data=try JSONSerialization.data(withJSONObject:rows)
print(String(data:data,encoding:.utf8)!)
