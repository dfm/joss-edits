import re
import subprocess
from hashlib import md5
from pathlib import Path
from urllib.parse import urlparse

import click
import yaml
from plumbum import local
import google.generativeai as genai

WORKDIR = Path(".joss")
JOURNAL_MACROS = list(
  sorted(
    [
      ["\\aas", "American Astronomical Society Meeting Abstracts"],
      ["\\aj", "Astronomical Journal"],
      ["\\actaa", "Acta Astronomica"],
      ["\\araa", "Annual Review of Astronomy and Astrophysics"],
      ["\\apj", "Astrophysical Journal"],
      ["\\apjl", "Astrophysical Journal, Letters"],
      ["\\apjs", "Astrophysical Journal, Supplement"],
      ["\\ao", "Applied Optics"],
      ["\\apss", "Astrophysics and Space Science"],
      ["\\aap", "Astronomy and Astrophysics"],
      ["\\aapr", "Astronomy and Astrophysics Reviews"],
      ["\\aaps", "Astronomy and Astrophysics, Supplement"],
      ["\\aplett", "Astrophysics Letters"],
      ["\\apspr", "Astrophysics Space Physics Research"],
      ["\\azh", "Astronomicheskii Zhurnal"],
      ["\\baas", "Bulletin of the AAS"],
      ["\\bain", "Bulletin Astronomical Institute of the Netherlands"],
      ["\\caa", "Chinese Astronomy and Astrophysics"],
      ["\\cjaa", "Chinese Journal of Astronomy and Astrophysics"],
      [
        "\\dps",
        "American Astronomical Society/Division for Planetary Sciences Meeting Abstracts",
      ],
      ["\\fcp", "Fundamental Cosmic Physics"],
      ["\\gca", "Geochimica Cosmochimica Acta"],
      ["\\grl", "Geophysics Research Letters"],
      ["\\iaucirc", "IAU Cirulars"],
      ["\\icarus", "Icarus"],
      ["\\jaavso", "Journal of the American Association of Variable Star Observers"],
      ["\\jcap", "Journal of Cosmology and Astroparticle Physics"],
      ["\\jcp", "Journal of Chemical Physics"],
      ["\\jgr", "Journal of Geophysics Research"],
      ["\\jqsrt", "Journal of Quantitiative Spectroscopy and Radiative Transfer"],
      ["\\jrasc", "Journal of the RAS of Canada"],
      ["\\maps", "Meteoritics and Planetary Science"],
      ["\\memras", "Memoirs of the RAS"],
      ["\\memsai", "Mem. Societa Astronomica Italiana"],
      ["\\mnras", "Monthly Notices of the RAS"],
      ["\\na", "New Astronomy"],
      ["\\nar", "New Astronomy Review"],
      ["\\nat", "Nature"],
      ["\\nphysa", "Nuclear Physics A"],
      ["\\pasa", "Publications of the Astron. Soc. of Australia"],
      ["\\pasp", "Publications of the ASP"],
      ["\\pasj", "Publications of the ASJ"],
      ["\\physrep", "Physics Reports"],
      ["\\physscr", "Physica Scripta"],
      ["\\planss", "Planetary Space Science"],
      ["\\pra", "Physical Review A: General Physics"],
      ["\\prb", "Physical Review B: Solid State"],
      ["\\prc", "Physical Review C"],
      ["\\prd", "Physical Review D"],
      ["\\pre", "Physical Review E"],
      ["\\prl", "Physical Review Letters"],
      ["\\procspie", "Proceedings of the SPIE"],
      ["\\psj", "Planetary Science Journal"],
      ["\\qjras", "Quarterly Journal of the RAS"],
      ["\\rmxaa", "Revista Mexicana de Astronomia y Astrofisica"],
      ["\\skytel", "Sky and Telescope"],
      ["\\solphys", "Solar Physics"],
      ["\\sovast", "Soviet Astronomy"],
      ["\\ssr", "Space Science Reviews"],
      ["\\zap", "Zeitschrift fuer Astrophysik"],
    ],
    key=lambda x: len(x[0]),
    reverse=True,
  )
)


@click.command()
@click.option("--branch", "-b", help="Edit a specific branch.")
@click.option("--copy-edit", "-c", "-e", "copy", help="Apply copy edits using Gemini.", is_flag=True)
@click.argument("repo")
def edit(repo: str, branch: str | None = None, copy: bool = False) -> None:
  """Copy edit and validate a JOSS paper."""
  path = clone(repo, branch)

  paper_path = find_paper(path)
  click.echo(f"Found paper at {paper_path.relative_to(path)}")

  bib = find_bib(paper_path)
  click.echo(f"Found bibliography at {bib.relative_to(path)}")

  fix_journal_macros(bib)
  click.echo("Fixed journal macros in bibliography")

  if copy:
    click.echo("Querying Gemini API for copy editing")
    copy_edit(paper_path)
    click.echo("Finished copy editing")

  fix_paper(paper_path)
  click.echo("Fixed paper format")

  subprocess.run([local["git"].executable, "diff"], cwd=path)


def workdir(repo: str, branch: str | None = None) -> Path:
  ident = Path(urlparse(repo).path).name
  if branch:
    ident += f"-{branch}"
  ident += f"-{md5(repo.encode()).hexdigest()[:7]}"
  path = WORKDIR / ident
  path.mkdir(exist_ok=True, parents=True)
  return path


def clone(repo: str, branch: str | None = None) -> Path:
  git = local["git"]
  path = workdir(repo, branch)
  if (path / ".git").exists():
    click.echo(f"Using existing checkout at {path}")
  else:
    click.echo(f"Cloning {repo} to {path}")
    args = ["clone", "--depth=1"]
    if branch:
      args += ["-b", branch]
    args += [repo]
    args += [path]
    git(*args)
    with local.cwd(local.cwd / path):
      git("checkout", "-b", f"edit-{branch or 'joss'}")
  return path


def find_paper(path: Path) -> Path:
  glob = path.glob("**/paper.md")
  try:
    return next(glob)
  except StopIteration:
    raise FileNotFoundError(f"Could not find paper.md in {path}")


def find_bib(paper_path: Path) -> dict:
  with paper_path.open() as f:
    txt = f.read()
  r = re.search(r"^(-{3}(?:\n|\r)([\w\W]+?)(?:\n|\r)-{3})?([\w\W]*)*", txt)
  if not r:
    raise ValueError(f"Could not extract frontmatter from {paper_path}")
  fm = yaml.safe_load(r.group(2))
  if "bibliography" not in fm:
    raise ValueError(f"No bibliography found in frontmatter of {paper_path}")
  bib = paper_path.parent / fm["bibliography"]
  if not bib.exists():
    raise FileNotFoundError(
      f"Bibliography expected at {bib}, but that file does not exist"
    )
  return bib


def fix_paper(paper_path: Path) -> None:
  with paper_path.open() as f:
    txt = f.read()
  txt = txt.rstrip()
  if txt.endswith("# References"):
    click.echo("Paper already has a references section header")
    return
  assert "# References" not in txt
  txt = txt + "\n\n# References\n"
  with paper_path.open("w") as f:
    f.write(txt)


def fix_journal_macros(bib_path: Path) -> None:
  with bib_path.open() as f:
    txt = f.read()
  for macro, journal in JOURNAL_MACROS:
    txt = txt.replace(macro, journal)
  with bib_path.open("w") as f:
    f.write(txt)


def copy_edit(paper_path: Path) -> None:
  with paper_path.open() as f:
    txt = f.read()
  nothing, fm, body = re.split("^---$", txt, flags=re.MULTILINE)
  assert not nothing

  genai.configure(api_key=open("api_key").read().strip())
  model = genai.GenerativeModel("gemini-1.5-pro")
  prompt = (
    "Please copy edit the markdown file which is included below and just print the "
    "edited document. Do not add a reference list, but do not remove or change "
    "references which are prefixed with an @ symbol. Do not to change the wrapping "
    "of the input. Do not change inline LaTeX commands which are indicated by a "
    "backslash, or math expressions which are delimited by $ signs.\n"
    f"Here is the markdown contents:\n\n{body}"
  )
  response = model.generate_content(prompt)
  text = response.text

  with open(paper_path, "w") as f:
    f.write(f"---\n{fm.strip()}\n---\n\n{text.strip()}\n")


if __name__ == "__main__":
  edit()
