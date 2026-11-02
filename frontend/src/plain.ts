/**
 * The models behind the counts are not named on screen: the screens say "it". Review reasons stored with older clips and
 * error messages from the API still name them, so text from the API goes through here before it is shown.
 */
const PHRASES: [RegExp, string][] = [
  [/(\d+) box\(es\) Spark disputes/, '$1 box(es) it could not confirm'],
  [/(\d+) box\(es\) with split Spark votes/, '$1 box(es) it was undecided about'],
  [/(\d+) carton\(s\) Spark sees with no box/, '$1 carton(s) it sees but has not outlined'],
  [/SAM found no object at that point/, 'It found no carton at that point'],
  [/\b(SAM|Spark) request failed/, 'The request failed'],
]

export function plain(text: string): string {
  let out = text
  for (const [pattern, to] of PHRASES) out = out.replace(pattern, to)
  return out.replace(/\b(SAM|Spark)\b/g, 'it')
}
