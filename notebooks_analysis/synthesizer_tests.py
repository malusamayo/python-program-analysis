import pandas as pd
import sys, pickle
sys.argv.append("./notebooks/debug_example.ipynb")

from analyzer import PatternSynthesizer, Info
from model import dispatch_gen


df1 = pd.read_csv('../notebooks/input/train.csv')

def test_case1():
    df2 = df1.copy()
    df2 = df1[~df1.isnull().any(axis=1)]
    df2['Sex'] = df2['Sex'].map({'male':0, 'female':1})
    checker = PatternSynthesizer(dispatch_gen(df1, "df1", 0, 0), dispatch_gen(df2, "df2", 0, 1), Info(None, None), [])
    l = checker.check(df1, df2)
    print("df1", "->","df2", "\033[96m", checker.summary, "\033[0m")

def test_case2():
    df2 = df1.copy()
    df2.drop(['Sex', 'Name'], axis=1)
    df2['Age'].fillna(0, inplace=True)
    print(id(df2.index), id(df2['Age'].index))
    # df2['Age'] = df2['Age'].map(lambda x: x + 1)
    df2['Age'] = df2['Age'].astype(str)
    df2.Survived = df2.Survived.astype(int)
    checker = PatternSynthesizer(dispatch_gen(df1, "df1", 0, 0), dispatch_gen(df2, "df2", 0, 1), Info(None, None), [])
    l = checker.check(df1, df2)
    print("df1", "->","df2", "\033[96m", checker.summary, "\033[0m")

def test_io():
    df2 = df1
    with open("test.dat", "wb") as f:
        pickle.dump([df1, df2], f)
    with open("test.dat", "rb") as f:
        vars = pickle.load(f)
        df1, df2 = vars[0], vars[1]
        checker = PatternSynthesizer(dispatch_gen(df1, "df1", 0, 0), dispatch_gen(df2, "df2", 0, 1), Info(None, None), [])
        l = checker.check(df1, df2)
        print("df1", "->","df2", "\033[96m", l, "\033[0m")

def test_double():
    df2 = df1.copy()
    df2.dropna(inplace=True)
    checker = PatternSynthesizer(dispatch_gen(df1, "df1", 0, 0), dispatch_gen(df2, "df2", 0, 1), Info(None, None), [])
    l = checker.check(df1, df2)
    print("df1", "->","df2", "\033[96m", checker.summary, "\033[0m")
    l = checker.check(df1, df2)
    print("df1", "->","df2", "\033[96m", checker.summary, "\033[0m")

def test_groupby():
    df2 = df1.copy()
    df2 = df2.groupby(['Name'])['Age'].sum()
    df2 = df2.reset_index()
    df2 = df2.sort_values('Age', ascending = False)
    checker = PatternSynthesizer(dispatch_gen(df1, "df1", 0, 0), dispatch_gen(df2, "df2", 0, 1), Info(None, None), [])
    l = checker.check(df1, df2)
    print("df1", "->","df2", "\033[96m", checker.summary, "\033[0m")


def run_all_tests():
    tests = [test_case1, test_case2, test_double, test_groupby]
    for test in tests:
        test()

run_all_tests()

# df['Happy'] = df['Age'].map(f)

# df['Puzzled'] = df['Age'].map(f) + df['Country'].map(g)

# df['Country'].map(g)
# df['Sad'] = df['Age'].map(f)

# df['Age'] = df['Age'].map(f) + df['Country'].map(g)
# df['Evil'] = df['Age'].map(f)
