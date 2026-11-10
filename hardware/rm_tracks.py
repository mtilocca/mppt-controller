import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1]); ids = set(open(sys.argv[2]).read().split())
gone = [t.m_Uuid.AsString() for t in b.GetTracks() if t.m_Uuid.AsString() in ids]
for t in list(b.GetTracks()):
    if t.m_Uuid.AsString() in gone: b.Remove(t)
print("removed", len(gone)); pcbnew.SaveBoard(sys.argv[1], b)
